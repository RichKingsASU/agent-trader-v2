from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

import requests

from backend.common.env import get_env
from backend.common.agent_mode import AgentModeError, require_live_mode as require_agent_live_mode
from backend.common.kill_switch import ExecutionHaltedError, get_kill_switch_state, is_kill_switch_enabled
from backend.common.runtime_execution_prevention import fatal_if_execution_reached
from backend.common.replay_events import build_replay_event, dumps_replay_event, set_replay_context
from backend.streams.alpaca_env import load_alpaca_env

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_date_utc(dt: datetime | None = None) -> str:
    d = (dt or _utc_now()).astimezone(timezone.utc).date()
    return d.isoformat()


def _to_jsonable(value: Any) -> Any:
    """
    Best-effort conversion to JSON-serializable data for audit logging / ledger writes.
    """
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _to_jsonable(v) for k, v in value.items()}
    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))
    return str(value)


@dataclass(frozen=True)
class OrderIntent:
    """
    Strategy → execution contract.

    Strict separation rule:
    - Strategies MUST NOT call brokers directly.
    - Strategies MUST emit intents only; execution decides whether/when/how to place.
    
    Supports multi-asset classes: Equities, Forex, Crypto, Options.
    """

    strategy_id: str
    broker_account_id: str
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    order_type: str = "market"  # "market" | "limit" | ...
    time_in_force: str = "day"
    limit_price: Optional[float] = None
    asset_class: str = "EQUITY"  # "EQUITY" | "FOREX" | "CRYPTO" | "OPTIONS"
    estimated_slippage: Optional[float] = None  # Estimated slippage percentage
    client_intent_id: str = field(default_factory=lambda: f"intent_{uuid.uuid4().hex}")
    created_at: datetime = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "OrderIntent":
        sym = (self.symbol or "").strip().upper()
        side = (self.side or "").strip().lower()
        order_type = (self.order_type or "").strip().lower()
        tif = (self.time_in_force or "").strip().lower()
        asset_class = (self.asset_class or "EQUITY").strip().upper()
        return OrderIntent(
            strategy_id=str(self.strategy_id),
            broker_account_id=str(self.broker_account_id),
            symbol=sym,
            side=side,
            qty=float(self.qty),
            order_type=order_type,
            time_in_force=tif,
            limit_price=self.limit_price,
            asset_class=asset_class,
            estimated_slippage=self.estimated_slippage,
            client_intent_id=str(self.client_intent_id),
            created_at=self.created_at,
            metadata=dict(self.metadata or {}),
        )


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SmartRoutingDecision:
    """
    Result of smart routing analysis including cost optimization.
    """
    should_execute: bool
    reason: str
    estimated_slippage: float
    spread_pct: float
    bid: float
    ask: float
    downgraded: bool = False  # True if signal was downgraded due to high costs


@dataclass(frozen=True)
class RiskConfig:
    """
    Minimal risk rules for the execution engine.
    """

    max_position_qty: float = 100.0
    max_daily_trades: int = 50
    fail_open: bool = False  # default fail-closed for safety

    @staticmethod
    def from_env() -> "RiskConfig":
        def _bool(name: str, default: bool) -> bool:
            v = os.getenv(name)
            if v is None:
                return default
            return str(v).strip().lower() in {"1", "true", "yes", "on"}

        def _float(name: str, default: float) -> float:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return float(v)

        def _int(name: str, default: int) -> int:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return int(v)

        return RiskConfig(
            max_position_qty=_float("EXEC_MAX_POSITION_QTY", 100.0),
            max_daily_trades=_int("EXEC_MAX_DAILY_TRADES", 50),
            fail_open=_bool("EXEC_RISK_FAIL_OPEN", False),
        )


@runtime_checkable
class Broker(Protocol):
    """
    Broker abstraction. Execution engine depends only on this interface.
    """

    def place_order(self, *, intent: OrderIntent) -> dict[str, Any]:
        """Returns broker order payload (raw dict)."""

    def cancel_order(self, *, broker_order_id: str) -> dict[str, Any]:
        """Returns broker cancel response (raw dict)."""

    def get_order_status(self, *, broker_order_id: str) -> dict[str, Any]:
        """Returns broker order payload (raw dict)."""


class DryRunBroker:
    """
    Broker implementation that never routes orders. Useful for validation / CI.
    """

    def place_order(self, *, intent: OrderIntent) -> dict[str, Any]:
        now = _utc_now()
        return {
            "id": f"dryrun_{uuid.uuid4().hex}",
            "status": "dry_run",
            "client_order_id": intent.client_intent_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "qty": str(intent.qty),
            "type": intent.order_type,
            "time_in_force": intent.time_in_force,
            "created_at": now.isoformat(),
            "filled_qty": "0",
        }

    def cancel_order(self, *, broker_order_id: str) -> dict[str, Any]:
        return {"id": broker_order_id, "status": "dry_run_canceled"}

    def get_order_status(self, *, broker_order_id: str) -> dict[str, Any]:
        return {"id": broker_order_id, "status": "dry_run"}


class MarketDataProvider:
    """
    Provides real-time market data for slippage estimation.
    Supports multiple asset classes via Alpaca API.
    """
    
    def __init__(self, *, request_timeout_s: float = 10.0):
        self._alpaca = load_alpaca_env(require_keys=True)
        self._data_base = self._alpaca.data_base_v2
        self._headers = {
            "APCA-API-KEY-ID": self._alpaca.key_id,
            "APCA-API-SECRET-KEY": self._alpaca.secret_key,
        }
        self._timeout = request_timeout_s
    
    def get_quote(self, *, symbol: str, asset_class: str = "EQUITY") -> dict[str, Any]:
        """
        Fetch latest quote (bid/ask) for a symbol.
        
        Returns dict with: bid, ask, spread, spread_pct, mid_price
        """
        try:
            # Map asset class to Alpaca endpoints
            if asset_class == "EQUITY":
                endpoint = f"{self._data_base}/stocks/{symbol}/quotes/latest"
            elif asset_class == "CRYPTO":
                # Crypto quotes endpoint
                endpoint = f"{self._data_base}/crypto/{symbol}/quotes/latest"
            elif asset_class == "FOREX":
                # Forex uses different format (remove slash)
                forex_symbol = symbol.replace("/", "")
                endpoint = f"{self._data_base}/forex/{forex_symbol}/quotes/latest"
            else:
                # Default to stocks
                endpoint = f"{self._data_base}/stocks/{symbol}/quotes/latest"
            
            r = requests.get(endpoint, headers=self._headers, timeout=self._timeout)
            r.raise_for_status()
            data = r.json()
            
            # Extract quote data
            quote = data.get("quote", {})
            bid = float(quote.get("bp") or quote.get("bid_price") or 0.0)
            ask = float(quote.get("ap") or quote.get("ask_price") or 0.0)
            
            if bid > 0 and ask > 0:
                spread = ask - bid
                mid_price = (bid + ask) / 2.0
                spread_pct = spread / mid_price if mid_price > 0 else 0.0
            else:
                spread = 0.0
                spread_pct = 0.0
                mid_price = bid or ask or 0.0
            
            return {
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "spread_pct": spread_pct,
                "mid_price": mid_price,
                "timestamp": quote.get("t") or quote.get("timestamp"),
            }
        except Exception as e:
            logger.warning("Failed to fetch quote for %s (%s): %s", symbol, asset_class, e)
            return {
                "bid": 0.0,
                "ask": 0.0,
                "spread": 0.0,
                "spread_pct": 0.0,
                "mid_price": 0.0,
                "error": str(e),
            }


class AlpacaBroker:
    """
    Minimal Alpaca Trading v2 REST broker.
    Supports multi-asset trading: Equities, Crypto, Forex.
    """

    def __init__(self, *, request_timeout_s: float = 10.0):
        self._alpaca = load_alpaca_env(require_keys=True)
        self._base = self._alpaca.trading_base_v2
        self._headers = {
            "APCA-API-KEY-ID": self._alpaca.key_id,
            "APCA-API-SECRET-KEY": self._alpaca.secret_key,
        }
        self._timeout = request_timeout_s

    def place_order(self, *, intent: OrderIntent) -> dict[str, Any]:
        fatal_if_execution_reached(
            operation="alpaca.place_order",
            explicit_message=(
                "Runtime execution is forbidden in agent-trader-v2. "
                "A broker submission attempt reached AlpacaBroker.place_order; aborting."
            ),
            context={
                "broker": "alpaca",
                "symbol": getattr(intent, "symbol", None),
                "side": getattr(intent, "side", None),
                "qty": getattr(intent, "qty", None),
                "client_intent_id": getattr(intent, "client_intent_id", None),
                "strategy_id": getattr(intent, "strategy_id", None),
                "broker_account_id": getattr(intent, "broker_account_id", None),
            },
        )
        payload: dict[str, Any] = {
            "symbol": intent.symbol,
            "qty": str(intent.qty),
            "side": intent.side,
            "type": intent.order_type,
            "time_in_force": intent.time_in_force,
            # Critical for audit/idempotency: tie broker order to strategy intent.
            "client_order_id": intent.client_intent_id,
        }
        if intent.order_type == "limit":
            if intent.limit_price is None:
                raise ValueError("limit_price is required for limit orders")
            payload["limit_price"] = str(intent.limit_price)

        r = requests.post(
            f"{self._base}/orders",
            headers=self._headers,
            json=payload,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()

    def cancel_order(self, *, broker_order_id: str) -> dict[str, Any]:
        fatal_if_execution_reached(
            operation="alpaca.cancel_order",
            explicit_message=(
                "Runtime execution is forbidden in agent-trader-v2. "
                "A broker cancel attempt reached AlpacaBroker.cancel_order; aborting."
            ),
            context={"broker": "alpaca", "broker_order_id": str(broker_order_id)},
        )
        r = requests.delete(
            f"{self._base}/orders/{broker_order_id}",
            headers=self._headers,
            timeout=self._timeout,
        )
        # Alpaca returns 204 for cancel success
        if r.status_code == 204:
            return {"id": broker_order_id, "status": "canceled"}
        r.raise_for_status()
        return r.json()

    def get_order_status(self, *, broker_order_id: str) -> dict[str, Any]:
        fatal_if_execution_reached(
            operation="alpaca.get_order_status",
            explicit_message=(
                "Runtime execution is forbidden in agent-trader-v2. "
                "A broker status poll reached AlpacaBroker.get_order_status; aborting."
            ),
            context={"broker": "alpaca", "broker_order_id": str(broker_order_id)},
        )
        r = requests.get(
            f"{self._base}/orders/{broker_order_id}",
            headers=self._headers,
            timeout=self._timeout,
        )
        r.raise_for_status()
        return r.json()


class _FirestoreLedger:
    """
    Ledger writer for fills. Writes immutable entries to:
      tenants/{tenant_id}/ledger_trades/{trade_id}
    """

    def __init__(self):
        from backend.persistence.firebase_client import get_firestore_client

        self._db = get_firestore_client()

    def _resolve_tenant_id(self, *, intent: OrderIntent) -> str:
        # Execution service is often internal (no end-user auth), so tenant context
        # must be provided out-of-band.
        tenant_id = str(intent.metadata.get("tenant_id") or "").strip()
        if not tenant_id:
            tenant_id = str(os.getenv("EXEC_TENANT_ID") or "").strip()
        if not tenant_id:
            raise ValueError(
                "Missing tenant_id for ledger write. Provide intent.metadata.tenant_id "
                "or set EXEC_TENANT_ID."
            )
        return tenant_id

    def _resolve_uid(self, *, intent: OrderIntent) -> str:
        uid = str(intent.metadata.get("uid") or "").strip()
        if not uid:
            uid = str(os.getenv("EXEC_UID") or "").strip()
        return uid or "system"

    def _resolve_run_id(self, *, intent: OrderIntent) -> str:
        # Prefer explicit run id; fall back to the intent id for traceability.
        run_id = str(intent.metadata.get("run_id") or "").strip()
        return run_id or str(intent.client_intent_id)

    def write_fill(
        self,
        *,
        intent: OrderIntent,
        broker: str,
        broker_order: dict[str, Any],
        fill: dict[str, Any],
    ) -> None:
        broker_order_id = str(broker_order.get("id") or "").strip()
        if not broker_order_id:
            raise ValueError("broker_order missing id")

        now = _utc_now()
        tenant_id = self._resolve_tenant_id(intent=intent)
        uid = self._resolve_uid(intent=intent)
        run_id = self._resolve_run_id(intent=intent)

        # Best-effort fill fields (Alpaca payloads vary by endpoint)
        filled_qty_raw = fill.get("filled_qty") or broker_order.get("filled_qty") or 0.0
        filled_avg_price_raw = fill.get("filled_avg_price") or broker_order.get("filled_avg_price") or None
        filled_at_raw = fill.get("filled_at") or broker_order.get("filled_at") or None

        filled_qty = float(filled_qty_raw or 0.0)
        if filled_qty <= 0:
            raise ValueError("Cannot write ledger trade with non-positive filled_qty")
        if filled_avg_price_raw is None:
            raise ValueError("Cannot write ledger trade without filled_avg_price")
        filled_avg_price = float(filled_avg_price_raw)
        if filled_avg_price <= 0:
            raise ValueError("Cannot write ledger trade with non-positive filled_avg_price")

        # Use fill timestamp when available; fall back to now.
        ts = now
        if isinstance(filled_at_raw, datetime):
            ts = filled_at_raw.astimezone(timezone.utc)

        # Compose a stable id that separates partial fills.
        broker_fill_fingerprint = f"{broker_order_id}|{filled_qty}|{filled_avg_price}|{filled_at_raw or ''}"

        from backend.ledger.firestore import append_ledger_trade, stable_trade_id

        trade_id = stable_trade_id(
            tenant_id=tenant_id,
            account_id=intent.broker_account_id,
            broker_fill_id=broker_fill_fingerprint,
            order_id=broker_order_id,
            ts=ts,
            symbol=intent.symbol,
        )

        payload: dict[str, Any] = {
            # Required schema fields (user spec)
            "uid": uid,
            "strategy_id": intent.strategy_id,
            "run_id": run_id,
            "symbol": intent.symbol,
            "side": intent.side,
            "qty": filled_qty,
            "price": filled_avg_price,
            "ts": ts,
            "fees": 0.0,
            # Multi-asset fields
            "asset_class": intent.asset_class,
            "estimated_slippage": intent.estimated_slippage,
            # Helpful optional fields for ops/audit
            "tenant_id": tenant_id,
            "trading_date": _iso_date_utc(ts),
            "broker": broker,
            "broker_order_id": broker_order_id,
            "broker_account_id": intent.broker_account_id,
            "client_intent_id": intent.client_intent_id,
            "intent_created_at": intent.created_at,
            "order_type": intent.order_type,
            "time_in_force": intent.time_in_force,
            "limit_price": intent.limit_price,
            "filled_at": _to_jsonable(filled_at_raw),
            # Raw snapshots for audit (JSON-safe)
            "raw_broker_order": _to_jsonable(broker_order),
            "raw_fill": _to_jsonable(fill),
        }

        # Append-only semantics: Firestore `create()` fails if doc exists.
        append_ledger_trade(tenant_id=tenant_id, trade_id=trade_id, payload=payload)

    def count_trades_today(self, *, tenant_id: str, broker_account_id: str, trading_date: str) -> int:
        q = (
            self._db.collection("tenants")
            .document(str(tenant_id))
            .collection("ledger_trades")
            .where("broker_account_id", "==", str(broker_account_id))
            .where("trading_date", "==", str(trading_date))
        )
        # Firestore count aggregation exists, but keep compatibility by streaming.
        return sum(1 for _ in q.stream())


class _PostgresPositions:
    """
    Optional position source from Postgres table `public.broker_positions`.

    If Postgres isn't configured, the engine will either fail-closed (default)
    or fail-open if EXEC_RISK_FAIL_OPEN=true.
    """

    def __init__(self, *, database_url: str):
        import psycopg

        self._psycopg = psycopg
        self._database_url = database_url

    def get_position_qty(self, *, symbol: str) -> float:
        with self._psycopg.connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT qty FROM public.broker_positions WHERE symbol = %s",
                    (symbol,),
                )
                row = cur.fetchone()
                if not row:
                    return 0.0
                return float(row[0] or 0.0)


class SmartRouter:
    """
    Smart routing engine for multi-asset cost optimization.
    
    Checks current market conditions (bid-ask spreads) and downgrades
    signals to WAIT if transaction costs are too high.
    """
    
    def __init__(
        self,
        *,
        market_data_provider: MarketDataProvider | None = None,
        max_spread_pct: float = 0.001,  # 0.1% default threshold
    ):
        self._market_data = market_data_provider
        self._max_spread_pct = max_spread_pct
    
    def analyze_intent(self, *, intent: OrderIntent) -> SmartRoutingDecision:
        """
        Analyze order intent and determine if it should be executed or downgraded.
        
        Returns SmartRoutingDecision with cost analysis.
        """
        # If we have a pre-computed slippage estimate, use it
        if intent.estimated_slippage is not None:
            if intent.estimated_slippage > self._max_spread_pct:
                return SmartRoutingDecision(
                    should_execute=False,
                    reason=f"Pre-computed slippage {intent.estimated_slippage:.4%} exceeds threshold {self._max_spread_pct:.4%}",
                    estimated_slippage=intent.estimated_slippage,
                    spread_pct=intent.estimated_slippage,
                    bid=0.0,
                    ask=0.0,
                    downgraded=True,
                )
            return SmartRoutingDecision(
                should_execute=True,
                reason="Pre-computed slippage within acceptable range",
                estimated_slippage=intent.estimated_slippage,
                spread_pct=intent.estimated_slippage,
                bid=0.0,
                ask=0.0,
                downgraded=False,
            )
        
        # Otherwise, fetch current market data
        try:
            if self._market_data is None:
                self._market_data = MarketDataProvider()
            
            quote = self._market_data.get_quote(symbol=intent.symbol, asset_class=intent.asset_class)
            
            # Check if we got valid quote data
            if quote.get("error"):
                logger.warning("Smart routing: failed to get quote for %s, allowing order", intent.symbol)
                return SmartRoutingDecision(
                    should_execute=True,
                    reason="Quote unavailable, proceeding with order",
                    estimated_slippage=0.0,
                    spread_pct=0.0,
                    bid=0.0,
                    ask=0.0,
                    downgraded=False,
                )
            
            spread_pct = quote["spread_pct"]
            
            # Downgrade if spread is too high
            if spread_pct > self._max_spread_pct:
                return SmartRoutingDecision(
                    should_execute=False,
                    reason=f"Spread {spread_pct:.4%} exceeds threshold {self._max_spread_pct:.4%}, downgrading to WAIT",
                    estimated_slippage=spread_pct,
                    spread_pct=spread_pct,
                    bid=quote["bid"],
                    ask=quote["ask"],
                    downgraded=True,
                )
            
            # Spread is acceptable, proceed
            return SmartRoutingDecision(
                should_execute=True,
                reason=f"Spread {spread_pct:.4%} within acceptable range",
                estimated_slippage=spread_pct,
                spread_pct=spread_pct,
                bid=quote["bid"],
                ask=quote["ask"],
                downgraded=False,
            )
        except Exception as e:
            # If market data fetch fails (e.g., missing API keys in test env), allow order
            logger.warning("Smart routing: error fetching quote for %s: %s, allowing order", intent.symbol, e)
            return SmartRoutingDecision(
                should_execute=True,
                reason="Market data unavailable, proceeding with order",
                estimated_slippage=0.0,
                spread_pct=0.0,
                bid=0.0,
                ask=0.0,
                downgraded=False,
            )


class RiskManager:
    def __init__(
        self,
        *,
        config: RiskConfig | None = None,
        ledger: _FirestoreLedger | None = None,
        positions: _PostgresPositions | None = None,
    ):
        self._config = config or RiskConfig.from_env()
        self._ledger = ledger
        self._positions = positions

    def kill_switch_enabled(self) -> bool:
        """
        Returns True if the execution kill-switch is enabled.

        This is a public wrapper around the internal kill-switch checks so
        execution agents can gate trading before attempting order routing.
        """
        return self._kill_switch_enabled()

    def _kill_switch_enabled(self) -> bool:
        # Standard global kill switch (env + optional file mount).
        if is_kill_switch_enabled():
            return True

        # Optional Firestore-backed kill switch (legacy; keep for back-compat).
        try:
            path = str(os.getenv("EXECUTION_HALTED_DOC") or os.getenv("EXEC_KILL_SWITCH_DOC") or "").strip().strip("/")
            if not path:
                return False
            parts = path.split("/")
            if len(parts) != 2:
                logger.warning("Invalid kill switch doc path: %s", path)
                return False
            col, doc = parts
            from backend.persistence.firebase_client import get_firestore_client

            db = get_firestore_client()
            snap = db.collection(col).document(doc).get()
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            return bool(data.get("enabled") is True)
        except Exception:
            return False

    def validate(self, *, intent: OrderIntent) -> RiskDecision:
        intent = intent.normalized()
        checks: list[dict[str, Any]] = []

        # Kill switch
        enabled = self.kill_switch_enabled()
        checks.append({"check": "kill_switch", "enabled": enabled})
        if enabled:
            return RiskDecision(allowed=False, reason="kill_switch_enabled", checks=checks)

        # Daily trades
        try:
            if self._ledger is None:
                self._ledger = _FirestoreLedger()
            today = _iso_date_utc()

            tenant_id: Optional[str] = None
            try:
                # Tenant-scoped ledger (preferred).
                tenant_id = self._ledger._resolve_tenant_id(intent=intent)  # type: ignore[attr-defined]
            except Exception:
                tenant_id = None

            # Back-compat: allow injected ledger stubs that don't take tenant_id.
            try:
                if tenant_id is not None:
                    trades_today = self._ledger.count_trades_today(
                        tenant_id=tenant_id,
                        broker_account_id=intent.broker_account_id,
                        trading_date=today,
                    )
                else:
                    trades_today = self._ledger.count_trades_today(
                        broker_account_id=intent.broker_account_id,
                        trading_date=today,
                    )
            except TypeError:
                trades_today = self._ledger.count_trades_today(
                    broker_account_id=intent.broker_account_id,
                    trading_date=today,
                )

            checks.append(
                {
                    "check": "max_daily_trades",
                    "today": today,
                    "trades_today": trades_today,
                    "limit": self._config.max_daily_trades,
                }
            )
            if tenant_id is not None:
                checks[-1]["tenant_id"] = tenant_id
            if trades_today >= self._config.max_daily_trades:
                return RiskDecision(allowed=False, reason="max_daily_trades_exceeded", checks=checks)
        except Exception as e:
            checks.append({"check": "max_daily_trades", "error": str(e)})
            if not self._config.fail_open:
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        # Position size
        try:
            database_url = os.getenv("DATABASE_URL")
            if self._positions is None and database_url:
                self._positions = _PostgresPositions(database_url=database_url)
            if self._positions is None:
                raise RuntimeError("positions provider not configured (set DATABASE_URL)")

            current_qty = self._positions.get_position_qty(symbol=intent.symbol)
            projected_qty = current_qty + (intent.qty if intent.side == "buy" else -intent.qty)
            checks.append(
                {
                    "check": "max_position_size",
                    "symbol": intent.symbol,
                    "current_qty": current_qty,
                    "projected_qty": projected_qty,
                    "limit_abs_qty": self._config.max_position_qty,
                }
            )
            if abs(projected_qty) > self._config.max_position_qty:
                return RiskDecision(allowed=False, reason="max_position_size_exceeded", checks=checks)
        except Exception as e:
            checks.append({"check": "max_position_size", "error": str(e)})
            if not self._config.fail_open:
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        return RiskDecision(allowed=True, reason="ok", checks=checks)


@dataclass(frozen=True)
class ExecutionResult:
    status: str  # "rejected" | "accepted" | "placed" | "dry_run" | "downgraded"
    risk: RiskDecision
    broker_order_id: Optional[str] = None
    broker_order: Optional[dict[str, Any]] = None
    message: Optional[str] = None
    routing: Optional[SmartRoutingDecision] = None  # Smart routing analysis


class ExecutionEngine:
    """
    Multi-Asset Smart Execution Engine that:
    - receives order intents (Equities, Forex, Crypto)
    - validates risk rules
    - analyzes transaction costs (bid-ask spreads)
    - downgrades signals when spreads > threshold
    - routes orders to a broker (or dry-run)
    - writes fills to the ledger AND users/{uid}/portfolio/history
    - logs everything (audit)
    """

    def __init__(
        self,
        *,
        broker: Broker,
        risk: RiskManager | None = None,
        router: SmartRouter | None = None,
        ledger: _FirestoreLedger | None = None,
        broker_name: str = "alpaca",
        dry_run: bool | None = None,
        enable_smart_routing: bool = False,  # Disabled by default for backward compatibility
    ):
        self._broker = broker
        self._risk = risk or RiskManager()
        self._router = router  # Lazy initialization if None and smart routing enabled
        self._ledger = ledger
        self._broker_name = broker_name
        self._dry_run = bool(dry_run) if dry_run is not None else bool(
            str(get_env("EXEC_DRY_RUN", "1")).strip().lower() in {"1", "true", "yes", "on"}
        )
        self._enable_smart_routing = enable_smart_routing

        # Replay marker: engine constructed (startup-ish for this component).
        try:
            set_replay_context(agent_name=os.getenv("AGENT_NAME") or "execution-engine")
            logger.info(
                "%s",
                dumps_replay_event(
                    build_replay_event(
                        event="startup",
                        component="backend.execution.engine",
                        data={
                            "broker_name": self._broker_name,
                            "dry_run": self._dry_run,
                            "enable_smart_routing": self._enable_smart_routing,
                            "router_provided": self._router is not None,
                        },
                    )
                ),
            )
        except Exception:
            pass

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def execute_intent(self, *, intent: OrderIntent) -> ExecutionResult:
        intent = intent.normalized()
        trace_id = str(
            intent.metadata.get("trace_id")
            or intent.metadata.get("run_id")
            or intent.client_intent_id
            or ""
        ).strip() or None
        if trace_id:
            set_replay_context(trace_id=trace_id)
        audit_ctx = {
            "client_intent_id": intent.client_intent_id,
            "strategy_id": intent.strategy_id,
            "broker_account_id": intent.broker_account_id,
            "symbol": intent.symbol,
            "asset_class": intent.asset_class,
            "side": intent.side,
            "qty": intent.qty,
            "order_type": intent.order_type,
            "time_in_force": intent.time_in_force,
            "limit_price": intent.limit_price,
            "estimated_slippage": intent.estimated_slippage,
        }
        logger.info("exec.intent_received %s", json.dumps(_to_jsonable(audit_ctx)))
        try:
            logger.info(
                "%s",
                dumps_replay_event(
                    build_replay_event(
                        event="order_intent",
                        component="backend.execution.engine",
                        data={
                            "stage": "received",
                            "intent": audit_ctx,
                        },
                        trace_id=trace_id,
                        agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                        run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                    )
                ),
            )
        except Exception:
            pass

        # Smart routing: check transaction costs BEFORE risk validation
        routing_decision = None
        if self._enable_smart_routing:
            # Lazy initialize router if not provided
            if self._router is None:
                self._router = SmartRouter()
            
            routing_decision = self._router.analyze_intent(intent=intent)
            logger.info(
                "exec.smart_routing %s",
                json.dumps(_to_jsonable({
                    "should_execute": routing_decision.should_execute,
                    "reason": routing_decision.reason,
                    "spread_pct": routing_decision.spread_pct,
                    "estimated_slippage": routing_decision.estimated_slippage,
                    "downgraded": routing_decision.downgraded,
                })),
            )
            try:
                logger.info(
                    "%s",
                    dumps_replay_event(
                        build_replay_event(
                            event="decision_checkpoint",
                            component="backend.execution.engine",
                            data={
                                "checkpoint": "smart_routing",
                                "should_execute": routing_decision.should_execute,
                                "reason": routing_decision.reason,
                                "spread_pct": routing_decision.spread_pct,
                                "estimated_slippage": routing_decision.estimated_slippage,
                                "downgraded": routing_decision.downgraded,
                                "symbol": intent.symbol,
                                "asset_class": intent.asset_class,
                            },
                            trace_id=trace_id,
                            agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                            run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                        )
                    ),
                )
            except Exception:
                pass
            
            if not routing_decision.should_execute:
                # Signal downgraded to WAIT due to high transaction costs
                risk = RiskDecision(allowed=False, reason="smart_routing_downgrade")
                try:
                    logger.info(
                        "%s",
                        dumps_replay_event(
                            build_replay_event(
                                event="state_transition",
                                component="backend.execution.engine",
                                data={
                                    "from_state": "risk_pending",
                                    "to_state": "downgraded",
                                    "reason": routing_decision.reason,
                                    "symbol": intent.symbol,
                                },
                                trace_id=trace_id,
                                agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                                run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                            )
                        ),
                    )
                except Exception:
                    pass
                return ExecutionResult(
                    status="downgraded",
                    risk=risk,
                    routing=routing_decision,
                    message=routing_decision.reason,
                )

        risk = self._risk.validate(intent=intent)
        logger.info(
            "exec.risk_decision %s",
            json.dumps(_to_jsonable({"allowed": risk.allowed, "reason": risk.reason, "checks": risk.checks})),
        )
        try:
            logger.info(
                "%s",
                dumps_replay_event(
                    build_replay_event(
                        event="decision_checkpoint",
                        component="backend.execution.engine",
                        data={
                            "checkpoint": "risk",
                            "allowed": risk.allowed,
                            "reason": risk.reason,
                            "symbol": intent.symbol,
                            "strategy_id": intent.strategy_id,
                            # checks can be large; keep but sanitized/size-limited.
                            "checks": risk.checks,
                        },
                        trace_id=trace_id,
                        agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                        run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                    )
                ),
            )
        except Exception:
            pass

        if not risk.allowed:
            try:
                logger.info(
                    "%s",
                    dumps_replay_event(
                        build_replay_event(
                            event="state_transition",
                            component="backend.execution.engine",
                            data={
                                "from_state": "risk_pending",
                                "to_state": "rejected",
                                "reason": risk.reason,
                                "symbol": intent.symbol,
                                "strategy_id": intent.strategy_id,
                            },
                            trace_id=trace_id,
                            agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                            run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                        )
                    ),
                )
            except Exception:
                pass
            return ExecutionResult(status="rejected", risk=risk, routing=routing_decision, message=risk.reason)

        if self._dry_run:
            logger.info("exec.dry_run_accept %s", json.dumps(_to_jsonable(audit_ctx)))
            try:
                logger.info(
                    "%s",
                    dumps_replay_event(
                        build_replay_event(
                            event="state_transition",
                            component="backend.execution.engine",
                            data={
                                "from_state": "risk_allowed",
                                "to_state": "dry_run_accepted",
                                "symbol": intent.symbol,
                                "strategy_id": intent.strategy_id,
                                "client_intent_id": intent.client_intent_id,
                            },
                            trace_id=trace_id,
                            agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                            run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                        )
                    ),
                )
            except Exception:
                pass
            return ExecutionResult(status="dry_run", risk=risk, routing=routing_decision, message="dry_run_enabled")

        # Defense-in-depth: never place broker orders if the global kill switch is active,
        # even if upstream risk checks were bypassed/misconfigured.
        if is_kill_switch_enabled():
            enabled, source = get_kill_switch_state()
            checks = list(risk.checks or [])
            checks.append({"check": "kill_switch", "enabled": bool(enabled), "source": source})
            halted_risk = RiskDecision(allowed=False, reason="kill_switch_enabled", checks=checks)
            return ExecutionResult(
                status="rejected",
                risk=halted_risk,
                routing=routing_decision,
                message="kill_switch_enabled",
            )

        # Authority boundary: even attempting a broker-side action requires explicit LIVE mode.
        # (This is separate from kill switch.)
        require_agent_live_mode(action="place_order")

        # Absolute safety boundary: runtime execution must be impossible even if misconfigured.
        fatal_if_execution_reached(
            operation="execution_engine.place_order",
            explicit_message=(
                "Runtime execution is forbidden in agent-trader-v2. "
                "ExecutionEngine reached the broker placement branch; aborting before broker call."
            ),
            context={
                "broker_name": self._broker_name,
                "symbol": intent.symbol,
                "side": intent.side,
                "qty": intent.qty,
                "client_intent_id": intent.client_intent_id,
                "strategy_id": intent.strategy_id,
                "broker_account_id": intent.broker_account_id,
                "asset_class": intent.asset_class,
            },
        )

        broker_order = self._broker.place_order(intent=intent)
        broker_order_id = str(broker_order.get("id") or "").strip() or None
        logger.info(
            "exec.order_placed %s",
            json.dumps(_to_jsonable({"broker": self._broker_name, "broker_order_id": broker_order_id, "order": broker_order})),
        )
        try:
            logger.info(
                "%s",
                dumps_replay_event(
                    build_replay_event(
                        event="order_intent",
                        component="backend.execution.engine",
                        data={
                            "stage": "broker_placed",
                            "broker": self._broker_name,
                            "broker_order_id": broker_order_id,
                            "client_intent_id": intent.client_intent_id,
                            "symbol": intent.symbol,
                            "side": intent.side,
                            "qty": intent.qty,
                            "order_type": intent.order_type,
                        },
                        trace_id=trace_id,
                        agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                        run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                    )
                ),
            )
        except Exception:
            pass

        # If immediately filled (or partially filled), write to ledger AND portfolio history.
        try:
            status = str(broker_order.get("status") or "").lower()
            filled_qty = float(broker_order.get("filled_qty") or 0.0)
            if status in {"filled", "partially_filled"} or filled_qty > 0:
                self._write_ledger_fill(intent=intent, broker_order=broker_order, fill=broker_order)
                self._write_portfolio_history(intent=intent, broker_order=broker_order, fill=broker_order)
        except Exception as e:
            logger.exception("exec.ledger_write_failed: %s", e)

        return ExecutionResult(
            status="placed",
            risk=risk,
            routing=routing_decision,
            broker_order_id=broker_order_id,
            broker_order=broker_order,
        )

    def cancel(self, *, broker_order_id: str) -> dict[str, Any]:
        logger.info(
            "exec.cancel_requested %s",
            json.dumps(_to_jsonable({"broker": self._broker_name, "broker_order_id": broker_order_id})),
        )
        if self._dry_run:
            return {"id": broker_order_id, "status": "dry_run"}
        fatal_if_execution_reached(
            operation="execution_engine.cancel_order",
            explicit_message=(
                "Runtime execution is forbidden in agent-trader-v2. "
                "ExecutionEngine.cancel() reached a broker cancel path; aborting."
            ),
            context={"broker_name": self._broker_name, "broker_order_id": str(broker_order_id)},
        )
        resp = self._broker.cancel_order(broker_order_id=broker_order_id)
        logger.info("exec.cancel_response %s", json.dumps(_to_jsonable(resp)))
        return resp

    def sync_and_ledger_if_filled(self, *, broker_order_id: str) -> dict[str, Any]:
        """
        Poll broker for status; if filled/partially_filled write/update ledger and portfolio history.
        """
        if self._dry_run:
            return {"id": broker_order_id, "status": "dry_run"}

        fatal_if_execution_reached(
            operation="execution_engine.get_order_status",
            explicit_message=(
                "Runtime execution is forbidden in agent-trader-v2. "
                "ExecutionEngine.sync_and_ledger_if_filled() reached a broker status poll; aborting."
            ),
            context={"broker_name": self._broker_name, "broker_order_id": str(broker_order_id)},
        )
        order = self._broker.get_order_status(broker_order_id=broker_order_id)
        logger.info(
            "exec.order_status %s",
            json.dumps(_to_jsonable({"broker_order_id": broker_order_id, "order": order})),
        )

        status = str(order.get("status") or "").lower()
        filled_qty = float(order.get("filled_qty") or 0.0)
        if status in {"filled", "partially_filled"} or filled_qty > 0:
            # We need the original intent to write a complete ledger record.
            # Best-effort: reconstruct from broker payload + metadata.
            intent = OrderIntent(
                strategy_id=str(order.get("client_order_id") or "unknown_strategy"),
                broker_account_id=str(order.get("account_id") or "unknown_account"),
                symbol=str(order.get("symbol") or ""),
                side=str(order.get("side") or ""),
                qty=float(order.get("qty") or 0.0),
                order_type=str(order.get("type") or "market"),
                time_in_force=str(order.get("time_in_force") or "day"),
                limit_price=float(order.get("limit_price")) if order.get("limit_price") else None,
                asset_class="EQUITY",  # Default, could be enhanced with metadata
                client_intent_id=str(order.get("client_order_id") or f"recon_{broker_order_id}"),
                created_at=_utc_now(),
                metadata={"reconstructed": True},
            ).normalized()
            self._write_ledger_fill(intent=intent, broker_order=order, fill=order)
            self._write_portfolio_history(intent=intent, broker_order=order, fill=order)
        return order

    def _write_ledger_fill(
        self, *, intent: OrderIntent, broker_order: dict[str, Any], fill: dict[str, Any]
    ) -> None:
        if self._ledger is None:
            self._ledger = _FirestoreLedger()
        self._ledger.write_fill(
            intent=intent,
            broker=self._broker_name,
            broker_order=broker_order,
            fill=fill,
        )
    
    def _write_portfolio_history(
        self, *, intent: OrderIntent, broker_order: dict[str, Any], fill: dict[str, Any]
    ) -> None:
        """
        Write trade to users/{uid}/portfolio/history for tax and performance tracking.
        
        This provides a user-facing trade history in addition to the internal ledger.
        """
        try:
            from backend.persistence.firebase_client import get_firestore_client
            
            db = get_firestore_client()
            
            # Resolve UID from intent metadata
            uid = str(intent.metadata.get("uid") or "").strip()
            if not uid:
                uid = str(os.getenv("EXEC_UID") or "").strip()
            if not uid or uid == "system":
                logger.warning("Skipping portfolio history write: no valid uid for %s", intent.symbol)
                return
            
            # Extract fill data
            broker_order_id = str(broker_order.get("id") or "").strip()
            filled_qty_raw = fill.get("filled_qty") or broker_order.get("filled_qty") or 0.0
            filled_avg_price_raw = fill.get("filled_avg_price") or broker_order.get("filled_avg_price") or None
            filled_at_raw = fill.get("filled_at") or broker_order.get("filled_at") or None
            
            filled_qty = float(filled_qty_raw or 0.0)
            if filled_qty <= 0:
                return
            
            filled_avg_price = float(filled_avg_price_raw) if filled_avg_price_raw else 0.0
            
            # Use fill timestamp when available; fall back to now
            ts = _utc_now()
            if isinstance(filled_at_raw, datetime):
                ts = filled_at_raw.astimezone(timezone.utc)
            
            # Create portfolio history entry
            history_id = f"{broker_order_id}_{int(ts.timestamp() * 1000)}"
            
            history_entry = {
                # Core trade data
                "symbol": intent.symbol,
                "asset_class": intent.asset_class,
                "side": intent.side,
                "qty": filled_qty,
                "price": filled_avg_price,
                "notional": filled_qty * filled_avg_price,
                "timestamp": ts,
                "trading_date": _iso_date_utc(ts),
                
                # Strategy and execution context
                "strategy_id": intent.strategy_id,
                "broker": self._broker_name,
                "broker_order_id": broker_order_id,
                "client_order_id": intent.client_intent_id,
                
                # Cost analysis
                "estimated_slippage": intent.estimated_slippage,
                "fees": 0.0,  # Update if broker provides fee data
                
                # Metadata
                "order_type": intent.order_type,
                "time_in_force": intent.time_in_force,
                "created_at": _utc_now(),
                
                # Tax tracking fields
                "tax_lot_method": "FIFO",  # Default to FIFO for tax purposes
                "cost_basis": filled_qty * filled_avg_price if intent.side == "buy" else None,
            }
            
            # Write to users/{uid}/portfolio/history/trades/{history_id}
            # Note: Using subcollection for scalability and tax year queries
            doc_ref = (
                db.collection("users")
                .document(uid)
                .collection("portfolio")
                .document("history")
                .collection("trades")
                .document(history_id)
            )
            doc_ref.set(history_entry)
            
            logger.info(
                "exec.portfolio_history_written uid=%s symbol=%s qty=%s price=%s",
                uid, intent.symbol, filled_qty, filled_avg_price
            )
            
        except Exception as e:
            logger.exception("Failed to write portfolio history: %s", e)

