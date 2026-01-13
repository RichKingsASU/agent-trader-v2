from __future__ import annotations

import json
import logging
import os
import time
import threading
import uuid
import hashlib
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable

import requests

from backend.common.env import get_env
from backend.common.agent_mode import require_live_mode as require_trading_live_mode
from backend.common.kill_switch import (
    ExecutionHaltedError,
    get_kill_switch_state,
    is_kill_switch_enabled,
    require_live_mode as require_kill_switch_off,
)
from backend.common.runtime_execution_prevention import fatal_if_execution_reached
from backend.common.replay_events import build_replay_event, dumps_replay_event, set_replay_context
from backend.common.freshness import check_freshness
from backend.time.nyse_time import parse_ts
from backend.streams.alpaca_env import load_alpaca_env
from backend.risk.capital_reservation import (
    CapitalReservationError,
    InsufficientBuyingPowerError,
    reserve_capital_atomic,
    release_capital_atomic,
)
from backend.vnext.risk_guard.interfaces import RiskGuardLimits, RiskGuardState, RiskGuardTrade, evaluate_risk_guard
from backend.observability.risk_signals import risk_correlation_id
from backend.execution.reservations import (
    BestEffortReservationManager,
    NoopReservation,
    ReservationHandle,
    ReservationManager,
    resolve_tenant_id_from_metadata,
)

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
    if is_dataclass(value):
        # Works for slots=True dataclasses as well.
        return _to_jsonable(asdict(value))
    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))
    return str(value)


class InvariantViolation(RuntimeError):
    """
    Raised when a risk/capital invariant is violated.

    Important: these are *not* normal risk rejections; they indicate internal
    accounting/state corruption or a contract breach between components.
    """


def _as_money_decimal(v: Any, *, name: str) -> Decimal:
    """
    Convert a numeric-ish value to Decimal for invariant checks.

    We accept string/float/int/Decimal since upstream may serialize money as strings.
    """
    if v is None:
        raise InvariantViolation(f"Missing required invariant field: {name}")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        # NOTE: float->str preserves human-visible value, not binary float;
        # this is best-effort for invariant checking.
        return Decimal(str(v))
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            raise InvariantViolation(f"Empty string is not a valid money value for {name}")
        return Decimal(s)
    raise InvariantViolation(f"Unsupported type for {name}: {type(v).__name__}")


def _fail_invariant(*, name: str, message: str, context: dict[str, Any]) -> None:
    ctx = {"invariant": name, **context}
    # Log at CRITICAL and then crash loudly.
    try:
        logger.critical("INVARIANT_VIOLATION %s %s", name, json.dumps(_to_jsonable(ctx)))
    except Exception:
        # Never swallow the crash if logging fails.
        pass
    raise InvariantViolation(f"{name}: {message} | context={ctx}")


def _enforce_risk_invariants_from_intent(*, intent: "OrderIntent") -> None:
    """
    Enforce risk/capital invariants encoded as intent metadata.

    Contract:
    - If a field is present, it MUST satisfy its invariant.
    - No silent correction; violations crash via InvariantViolation.
    - These checks are for *internal consistency* and "should never happen" states.
    """
    md = dict(intent.metadata or {})

    def _get_any(*keys: str) -> Any:
        for k in keys:
            if k in md:
                return md.get(k)
        return None

    # Invariant: available_capital >= 0
    av = _get_any("available_capital", "buying_power")
    if av is not None:
        available_capital = _as_money_decimal(av, name="available_capital")
        if available_capital < 0:
            _fail_invariant(
                name="available_capital_non_negative",
                message=f"available_capital is negative ({available_capital})",
                context={"available_capital": available_capital},
            )

    # Invariant: total_reserved <= daily_capital
    tr = _get_any("total_reserved", "reserved_capital")
    dc = _get_any("daily_capital")
    if tr is not None or dc is not None:
        if tr is None or dc is None:
            _fail_invariant(
                name="total_reserved_lte_daily_capital",
                message="partial reservation state: both total_reserved and daily_capital must be provided together",
                context={"total_reserved_present": tr is not None, "daily_capital_present": dc is not None},
            )
        total_reserved = _as_money_decimal(tr, name="total_reserved")
        daily_capital = _as_money_decimal(dc, name="daily_capital")
        if total_reserved < 0:
            _fail_invariant(
                name="total_reserved_non_negative",
                message=f"total_reserved is negative ({total_reserved})",
                context={"total_reserved": total_reserved, "daily_capital": daily_capital},
            )
        if daily_capital < 0:
            _fail_invariant(
                name="daily_capital_non_negative",
                message=f"daily_capital is negative ({daily_capital})",
                context={"total_reserved": total_reserved, "daily_capital": daily_capital},
            )
        if total_reserved > daily_capital:
            _fail_invariant(
                name="total_reserved_lte_daily_capital",
                message=f"total_reserved ({total_reserved}) exceeds daily_capital ({daily_capital})",
                context={"total_reserved": total_reserved, "daily_capital": daily_capital},
            )

    # Invariant: daily_risk_used <= cap
    dru = _get_any("daily_risk_used")
    drc = _get_any("daily_risk_cap", "daily_risk_limit")
    if dru is not None or drc is not None:
        if dru is None or drc is None:
            _fail_invariant(
                name="daily_risk_used_lte_cap",
                message="partial daily risk state: both daily_risk_used and daily_risk_cap must be provided together",
                context={"daily_risk_used_present": dru is not None, "daily_risk_cap_present": drc is not None},
            )
        daily_risk_used = _as_money_decimal(dru, name="daily_risk_used")
        daily_risk_cap = _as_money_decimal(drc, name="daily_risk_cap")
        if daily_risk_used < 0:
            _fail_invariant(
                name="daily_risk_used_non_negative",
                message=f"daily_risk_used is negative ({daily_risk_used})",
                context={"daily_risk_used": daily_risk_used, "daily_risk_cap": daily_risk_cap},
            )
        if daily_risk_cap < 0:
            _fail_invariant(
                name="daily_risk_cap_non_negative",
                message=f"daily_risk_cap is negative ({daily_risk_cap})",
                context={"daily_risk_used": daily_risk_used, "daily_risk_cap": daily_risk_cap},
            )
        if daily_risk_used > daily_risk_cap:
            _fail_invariant(
                name="daily_risk_used_lte_cap",
                message=f"daily_risk_used ({daily_risk_used}) exceeds daily_risk_cap ({daily_risk_cap})",
                context={"daily_risk_used": daily_risk_used, "daily_risk_cap": daily_risk_cap},
            )


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


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        # Only accept whole floats (avoid surprising truncation).
        if float(value).is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            return None
    return None


@dataclass(frozen=True)
class AgentExecutionBudget:
    """
    Per-agent execution budget for a single UTC day.

    - max_daily_executions: maximum number of allowed executions (risk-approved intents)
    - max_daily_capital_pct: maximum fraction of daily capital deployable by this agent (0..1]
    """

    max_daily_executions: int | None = None
    max_daily_capital_pct: float | None = None

    def normalized(self) -> "AgentExecutionBudget":
        mde = self.max_daily_executions
        if mde is not None and mde < 0:
            mde = 0
        pct = self.max_daily_capital_pct
        if pct is not None:
            pct = float(pct)
            # Support "percent" inputs like 10 => 10%.
            if pct > 1.0:
                pct = pct / 100.0
            if pct < 0.0:
                pct = 0.0
        return AgentExecutionBudget(max_daily_executions=mde, max_daily_capital_pct=pct)

    def is_effectively_unlimited(self) -> bool:
        b = self.normalized()
        no_exec_cap = b.max_daily_executions is None
        no_capital_cap = (b.max_daily_capital_pct is None) or (b.max_daily_capital_pct >= 1.0)
        return bool(no_exec_cap and no_capital_cap)


@dataclass
class _AgentBudgetUsage:
    executions_used: int = 0
    notional_used_usd: float = 0.0



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
        # Absolute safety boundary: never attempt broker-side order placement while halted.
        # This ensures retries/replays cannot bypass upstream guards.
        require_kill_switch_off(operation="alpaca.place_order")
        # --- PAPER TRADING OVERRIDE (START) ---
        # Allow paper trading if TRADING_MODE is 'paper' and Alpaca base URL is paper.
        is_paper_mode = os.getenv("TRADING_MODE", "").strip().lower() == "paper"
        is_alpaca_paper_url = "paper-api.alpaca.markets" in self._alpaca.trading_base_v2

        if is_paper_mode and is_alpaca_paper_url:
            logger.info(
                "Paper trading enabled: Bypassing fatal_if_execution_reached for alpaca.place_order "
                "(TRADING_MODE=paper and APCA_API_BASE_URL is paper-api.alpaca.markets)"
            )
        else:
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
                    "is_paper_mode": is_paper_mode,
                    "is_alpaca_paper_url": is_alpaca_paper_url,
                    "alpaca_base_url": self._alpaca.trading_base_v2,
                },
            )
        # --- PAPER TRADING OVERRIDE (END) ---
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
        # Even cancellations are broker-side actions; refuse while halted.
        require_kill_switch_off(operation="alpaca.cancel_order")
        # --- PAPER TRADING OVERRIDE (START) ---
        # Allow paper trading if TRADING_MODE is 'paper' and Alpaca base URL is paper.
        is_paper_mode = os.getenv("TRADING_MODE", "").strip().lower() == "paper"
        is_alpaca_paper_url = "paper-api.alpaca.markets" in self._alpaca.trading_base_v2

        if is_paper_mode and is_alpaca_paper_url:
            logger.info(
                "Paper trading enabled: Bypassing fatal_if_execution_reached for alpaca.cancel_order "
                "(TRADING_MODE=paper and APCA_API_BASE_URL is paper-api.alpaca.markets)"
            )
        else:
            fatal_if_execution_reached(
                operation="alpaca.cancel_order",
                explicit_message=(
                    "Runtime execution is forbidden in agent-trader-v2. "
                    "A broker cancel attempt reached AlpacaBroker.cancel_order; aborting."
                ),
                context={"broker": "alpaca", "broker_order_id": str(broker_order_id)},
            )
        # --- PAPER TRADING OVERRIDE (END) ---
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
        # Status polls are not executions, but they do hit the broker API; keep halt semantics consistent.
        require_kill_switch_off(operation="alpaca.get_order_status")
        # --- PAPER TRADING OVERRIDE (START) ---
        # Allow paper trading if TRADING_MODE is 'paper' and Alpaca base URL is paper.
        is_paper_mode = os.getenv("TRADING_MODE", "").strip().lower() == "paper"
        is_alpaca_paper_url = "paper-api.alpaca.markets" in self._alpaca.trading_base_v2

        if is_paper_mode and is_alpaca_paper_url:
            logger.info(
                "Paper trading enabled: Bypassing fatal_if_execution_reached for alpaca.get_order_status "
                "(TRADING_MODE=paper and APCA_API_BASE_URL is paper-api.alpaca.markets)"
            )
        else:
            fatal_if_execution_reached(
                operation="alpaca.get_order_status",
                explicit_message=(
                    "Runtime execution is forbidden in agent-trader-v2. "
                    "A broker status poll reached AlpacaBroker.get_order_status; aborting."
                ),
                context={"broker": "alpaca", "broker_order_id": str(broker_order_id)},
            )
        # --- PAPER TRADING OVERRIDE (END) ---
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


class _FirestoreRiskLimitsProvider:
    """
    Best-effort read of Firestore-backed risk limits (tenant-scoped).

    Collection:
      tenants/{tenant_id}/risk_limits/{doc}

    Notes:
    - The risk service uses these docs for /risk/check-trade.
    - Execution engine reads them to enforce limits *before* broker placement.
    """

    _COLLECTION = "risk_limits"

    def __init__(self):
        from backend.persistence.firebase_client import get_firestore_client

        self._db = get_firestore_client()

    def get_enabled_limits(
        self,
        *,
        tenant_id: str,
        uid: str,
        broker_account_id: str,
        scope: str,
        strategy_id: str | None,
    ) -> dict[str, Any] | None:
        if not tenant_id or not uid or not broker_account_id:
            return None
        q = (
            self._db.collection("tenants")
            .document(str(tenant_id))
            .collection(self._COLLECTION)
            .where("uid", "==", str(uid))
            .where("broker_account_id", "==", str(broker_account_id))
            .where("scope", "==", str(scope))
            .where("enabled", "==", True)
        )
        if scope == "strategy":
            q = q.where("strategy_id", "==", str(strategy_id or ""))
        docs = list(q.limit(1).stream())
        if not docs:
            return None
        d = docs[0].to_dict() or {}
        # Helpful for audit/debugging.
        d["id"] = docs[0].id
        return d


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

        # --- Per-agent execution budgets (silent safety) ---
        self._budgets_enabled = str(os.getenv("EXEC_AGENT_BUDGETS_ENABLED") or "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._budgets_use_firestore = str(os.getenv("EXEC_AGENT_BUDGETS_USE_FIRESTORE") or "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._budgets_fail_open = str(os.getenv("EXEC_AGENT_BUDGETS_FAIL_OPEN") or "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._budget_cache_s = float(os.getenv("EXEC_AGENT_BUDGET_CACHE_S") or "60")

        default_execs = _as_int_or_none(os.getenv("EXEC_AGENT_DEFAULT_MAX_DAILY_EXECUTIONS"))
        default_pct = _as_float_or_none(os.getenv("EXEC_AGENT_DEFAULT_MAX_DAILY_CAPITAL_PCT"))
        self._default_budget = AgentExecutionBudget(
            max_daily_executions=default_execs,
            max_daily_capital_pct=default_pct,
        ).normalized()

        # Optional per-agent overrides via env JSON:
        #   EXEC_AGENT_BUDGETS_JSON='{"agent_a":{"max_daily_executions":5,"max_daily_capital_pct":0.1}}'
        self._budget_overrides: dict[str, AgentExecutionBudget] = {}
        raw_overrides = str(os.getenv("EXEC_AGENT_BUDGETS_JSON") or "").strip()
        if raw_overrides:
            try:
                obj = json.loads(raw_overrides)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if not isinstance(k, str) or not isinstance(v, dict):
                            continue
                        self._budget_overrides[k.strip()] = AgentExecutionBudget(
                            max_daily_executions=_as_int_or_none(v.get("max_daily_executions")),
                            max_daily_capital_pct=_as_float_or_none(v.get("max_daily_capital_pct")),
                        ).normalized()
            except Exception:
                # Never crash startup for config parse issues; budgets remain default-only.
                pass

        # Cache budgets read from Firestore: (tenant_id, agent_id) -> (cached_at_mono, budget)
        self._budget_cache: dict[tuple[str, str], tuple[float, AgentExecutionBudget]] = {}

        # Local fallback usage store (also used in unit tests). Keyed by tenant|agent|date.
        self._budget_usage_lock = threading.Lock()
        self._budget_usage_local: dict[str, _AgentBudgetUsage] = {}

    def _firestore_consume_budget_usage(
        self,
        *,
        tenant_id: str,
        agent_id: str,
        trading_date: str,
        proposed_execs: int,
        proposed_notional_usd: float,
        budget: AgentExecutionBudget,
        daily_capital_usd: float | None,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Atomically check+consume budget usage in Firestore.

        Returns (allowed, usage_snapshot).
        """
        from google.cloud import firestore  # type: ignore
        from backend.persistence.firebase_client import get_firestore_client

        b = budget.normalized()
        db = get_firestore_client()
        doc_ref = (
            db.collection("tenants")
            .document(str(tenant_id))
            .collection("agent_execution_usage")
            .document(f"{agent_id}__{trading_date}")
        )

        usage_snapshot: dict[str, Any] = {}

        @firestore.transactional
        def _txn(txn):  # type: ignore[no-untyped-def]
            snap = doc_ref.get(transaction=txn)
            data = snap.to_dict() if getattr(snap, "exists", False) else {}
            execs_used = int(_as_int_or_none((data or {}).get("executions_used")) or 0)
            notional_used = float(_as_float_or_none((data or {}).get("notional_used_usd")) or 0.0)

            execs_next = execs_used + int(proposed_execs)
            notional_next = notional_used + float(proposed_notional_usd)

            # Check execution cap
            if b.max_daily_executions is not None and execs_next > int(b.max_daily_executions):
                usage_snapshot.update(
                    {
                        "executions_used": execs_used,
                        "notional_used_usd": notional_used,
                        "executions_next": execs_next,
                        "notional_next_usd": notional_next,
                    }
                )
                raise RuntimeError("budget_exceeded:max_daily_executions")

            # Check capital pct cap
            if (
                b.max_daily_capital_pct is not None
                and b.max_daily_capital_pct < 1.0
                and daily_capital_usd is not None
                and daily_capital_usd > 0
            ):
                limit_notional = float(daily_capital_usd) * float(b.max_daily_capital_pct)
                if notional_next > limit_notional:
                    usage_snapshot.update(
                        {
                            "executions_used": execs_used,
                            "notional_used_usd": notional_used,
                            "executions_next": execs_next,
                            "notional_next_usd": notional_next,
                            "notional_limit_usd": limit_notional,
                        }
                    )
                    raise RuntimeError("budget_exceeded:max_daily_capital_pct")

            payload = {
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "trading_date": trading_date,
                "executions_used": execs_next,
                "notional_used_usd": notional_next,
                "updated_at": firestore.SERVER_TIMESTAMP,
                "updated_at_iso": _utc_now().isoformat(),
            }
            txn.set(doc_ref, payload, merge=True)
            usage_snapshot.update(
                {
                    "executions_used": execs_next,
                    "notional_used_usd": notional_next,
                }
            )

        txn = db.transaction()
        try:
            _txn(txn)
            return True, usage_snapshot
        except RuntimeError as e:
            if str(e).startswith("budget_exceeded:"):
                usage_snapshot.setdefault("error", str(e))
                return False, usage_snapshot
            raise

    def _resolve_agent_id(self, *, intent: OrderIntent) -> str:
        md = dict(intent.metadata or {})
        for k in ("agent_id", "agentId", "agent_name", "agentName"):
            v = md.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        # Fall back to strategy_id (best available stable identity).
        return str(intent.strategy_id).strip() or "unknown_agent"

    def _resolve_tenant_id_from_intent(self, *, intent: OrderIntent) -> str | None:
        md = dict(intent.metadata or {})
        v = md.get("tenant_id") or md.get("tenantId") or os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID")
        if isinstance(v, str) and v.strip():
            return v.strip()
        return None

    def _resolve_uid_from_intent(self, *, intent: OrderIntent) -> str | None:
        md = dict(intent.metadata or {})
        v = md.get("uid") or md.get("user_id") or md.get("userId") or os.getenv("USER_ID") or os.getenv("EXEC_UID")
        if isinstance(v, str) and v.strip():
            return v.strip()
        return None

    def _resolve_budget(self, *, tenant_id: str | None, agent_id: str) -> AgentExecutionBudget:
        """
        Resolve the effective budget for (tenant, agent):
        - Firestore override (best-effort, cached)
        - Env JSON override
        - Env defaults
        """
        agent_id = str(agent_id or "").strip() or "unknown_agent"

        # Start with defaults; layer overrides on top.
        budget = self._default_budget
        if agent_id in self._budget_overrides:
            # Override is absolute (not merged) to keep behavior predictable.
            budget = self._budget_overrides[agent_id]

        if not self._budgets_use_firestore or tenant_id is None:
            return budget.normalized()

        cache_key = (str(tenant_id), agent_id)
        now_mono = time.monotonic()
        cached = self._budget_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_budget = cached
            if (now_mono - cached_at) <= float(self._budget_cache_s):
                # Merge cached Firestore config over env config.
                fb = cached_budget.normalized()
                merged = AgentExecutionBudget(
                    max_daily_executions=fb.max_daily_executions if fb.max_daily_executions is not None else budget.max_daily_executions,
                    max_daily_capital_pct=fb.max_daily_capital_pct if fb.max_daily_capital_pct is not None else budget.max_daily_capital_pct,
                )
                return merged.normalized()

        # Best-effort Firestore read.
        try:
            from backend.persistence.firebase_client import get_firestore_client

            db = get_firestore_client()
            doc = (
                db.collection("tenants")
                .document(str(tenant_id))
                .collection("agent_execution_budgets")
                .document(agent_id)
                .get()
            )
            data = doc.to_dict() if getattr(doc, "exists", False) else None
            fs_budget = AgentExecutionBudget(
                max_daily_executions=_as_int_or_none((data or {}).get("max_daily_executions")),
                max_daily_capital_pct=_as_float_or_none((data or {}).get("max_daily_capital_pct")),
            ).normalized()
            self._budget_cache[cache_key] = (now_mono, fs_budget)
            merged = AgentExecutionBudget(
                max_daily_executions=fs_budget.max_daily_executions if fs_budget.max_daily_executions is not None else budget.max_daily_executions,
                max_daily_capital_pct=fs_budget.max_daily_capital_pct if fs_budget.max_daily_capital_pct is not None else budget.max_daily_capital_pct,
            )
            return merged.normalized()
        except Exception:
            # Firestore unavailable: fall back to env config.
            return budget.normalized()

    def _estimate_intent_notional_usd(self, *, intent: OrderIntent) -> float | None:
        """
        Best-effort notional estimate, in USD.
        """
        md = dict(intent.metadata or {})
        for k in (
            "notional_usd",
            "notionalUsd",
            "notional",
            "suggested_notional",
            "suggestedNotional",
            "order_notional_usd",
        ):
            v = _as_float_or_none(md.get(k))
            if v is not None and v > 0:
                return float(abs(v))

        if intent.limit_price is not None and float(intent.limit_price) > 0:
            return float(abs(float(intent.qty) * float(intent.limit_price)))

        # As a last resort, try a quote mid price (best-effort; can fail in CI).
        try:
            quote = MarketDataProvider().get_quote(symbol=intent.symbol, asset_class=intent.asset_class)
            mid = _as_float_or_none(quote.get("mid_price"))
            if mid is None or mid <= 0:
                return None
            return float(abs(float(intent.qty) * float(mid)))
        except Exception:
            return None

    def _resolve_daily_capital_usd(self, *, intent: OrderIntent, tenant_id: str | None, uid: str | None) -> float | None:
        """
        Resolve the 'daily capital' baseline for budget enforcement.
        Prefers explicit metadata; otherwise reads warm-cache account snapshot (equity/buying_power).
        """
        md = dict(intent.metadata or {})
        for k in ("daily_capital_usd", "dailyCapitalUsd", "portfolio_value", "equity", "buying_power"):
            v = _as_float_or_none(md.get(k))
            if v is not None and v > 0:
                return float(v)

        # Fallback: read from Firestore warm-cache snapshot.
        try:
            from backend.persistence.firebase_client import get_firestore_client

            db = get_firestore_client()
            snap = None
            if uid:
                snap = (
                    db.collection("users")
                    .document(str(uid))
                    .collection("alpacaAccounts")
                    .document("snapshot")
                    .get()
                )
            elif tenant_id:
                snap = db.collection("tenants").document(str(tenant_id)).collection("accounts").document("primary").get()
            if not snap or not getattr(snap, "exists", False):
                return None
            data = snap.to_dict() or {}
            equity = _as_float_or_none(data.get("equity"))
            if equity is not None and equity > 0:
                return float(equity)
            buying_power = _as_float_or_none(data.get("buying_power"))
            if buying_power is not None and buying_power > 0:
                return float(buying_power)
            return None
        except Exception:
            return None

    def _consume_agent_budget_or_reject(self, *, intent: OrderIntent, checks: list[dict[str, Any]]) -> RiskDecision | None:
        """
        Side-effecting budget enforcement.

        Returns a rejecting RiskDecision if caps are hit; otherwise returns None.
        """
        if not self._budgets_enabled:
            return None

        agent_id = self._resolve_agent_id(intent=intent)
        tenant_id = self._resolve_tenant_id_from_intent(intent=intent)
        uid = self._resolve_uid_from_intent(intent=intent)
        today = _iso_date_utc()
        budget = self._resolve_budget(tenant_id=tenant_id, agent_id=agent_id)

        # If budgets are not configured, don't block.
        if budget.is_effectively_unlimited():
            checks.append(
                {
                    "check": "agent_execution_budget",
                    "enabled": True,
                    "effective": "unlimited",
                    "agent_id": agent_id,
                    "tenant_id": tenant_id,
                    "today": today,
                }
            )
            return None

        proposed_execs = 1
        proposed_notional = self._estimate_intent_notional_usd(intent=intent)

        daily_capital = None
        if budget.max_daily_capital_pct is not None and budget.max_daily_capital_pct < 1.0:
            daily_capital = self._resolve_daily_capital_usd(intent=intent, tenant_id=tenant_id, uid=uid)

        if budget.max_daily_capital_pct is not None and budget.max_daily_capital_pct < 1.0:
            if daily_capital is None or daily_capital <= 0:
                checks.append(
                    {
                        "check": "agent_execution_budget",
                        "enabled": True,
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "today": today,
                        "error": "daily_capital_unavailable",
                    }
                )
                logger.warning(
                    "exec.agent_budget_refused %s",
                    json.dumps(
                        _to_jsonable(
                            {
                                "event_type": "risk",
                                "intent_type": "agent_execution_budget_refused",
                                "agent_id": agent_id,
                                "strategy_id": intent.strategy_id,
                                "tenant_id": tenant_id,
                                "uid": uid,
                                "trading_date": today,
                                "reason": "daily_capital_unavailable",
                            }
                        )
                    ),
                )
                return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=checks)

            if proposed_notional is None or proposed_notional <= 0:
                checks.append(
                    {
                        "check": "agent_execution_budget",
                        "enabled": True,
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "today": today,
                        "daily_capital_usd": daily_capital,
                        "error": "notional_unavailable",
                    }
                )
                logger.warning(
                    "exec.agent_budget_refused %s",
                    json.dumps(
                        _to_jsonable(
                            {
                                "event_type": "risk",
                                "intent_type": "agent_execution_budget_refused",
                                "agent_id": agent_id,
                                "strategy_id": intent.strategy_id,
                                "tenant_id": tenant_id,
                                "uid": uid,
                                "trading_date": today,
                                "reason": "notional_unavailable",
                            }
                        )
                    ),
                )
                return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=checks)

        # Preferred enforcement: Firestore transaction for cross-instance correctness.
        if self._budgets_use_firestore and tenant_id is not None and not budget.is_effectively_unlimited():
            try:
                allowed, usage = self._firestore_consume_budget_usage(
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    trading_date=today,
                    proposed_execs=proposed_execs,
                    proposed_notional_usd=float(proposed_notional or 0.0),
                    budget=budget,
                    daily_capital_usd=daily_capital,
                )
                if not allowed:
                    # Determine which cap was hit from the error.
                    err = str((usage or {}).get("error") or "")
                    cap_hit = "unknown"
                    if "max_daily_executions" in err:
                        cap_hit = "max_daily_executions"
                    elif "max_daily_capital_pct" in err:
                        cap_hit = "max_daily_capital_pct"
                    cap_check = {
                        "check": "agent_execution_budget",
                        "enabled": True,
                        "cap_hit": cap_hit,
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "today": today,
                        "executions_used": usage.get("executions_used"),
                        "notional_used_usd": usage.get("notional_used_usd"),
                        "executions_proposed": proposed_execs,
                        "notional_proposed_usd": proposed_notional,
                        "max_daily_executions": budget.max_daily_executions,
                        "max_daily_capital_pct": budget.max_daily_capital_pct,
                        "daily_capital_usd": daily_capital,
                        "note": "enforced_via_firestore_transaction",
                    }
                    checks.append(cap_check)
                    logger.warning("exec.agent_budget_cap_hit %s", json.dumps(_to_jsonable(cap_check)))
                    return RiskDecision(allowed=False, reason="agent_execution_budget_exceeded", checks=checks)

                checks.append(
                    {
                        "check": "agent_execution_budget",
                        "enabled": True,
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "today": today,
                        "executions_used_after": usage.get("executions_used"),
                        "notional_used_usd_after": usage.get("notional_used_usd"),
                        "max_daily_executions": budget.max_daily_executions,
                        "max_daily_capital_pct": budget.max_daily_capital_pct,
                        "note": "enforced_via_firestore_transaction",
                    }
                )
                return None
            except Exception as e:
                # Firestore unavailable: fail-closed unless explicitly configured otherwise.
                checks.append(
                    {
                        "check": "agent_execution_budget",
                        "enabled": True,
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "today": today,
                        "error": f"firestore_unavailable:{type(e).__name__}",
                    }
                )
                logger.warning(
                    "exec.agent_budget_refused %s",
                    json.dumps(
                        _to_jsonable(
                            {
                                "event_type": "risk",
                                "intent_type": "agent_execution_budget_refused",
                                "agent_id": agent_id,
                                "strategy_id": intent.strategy_id,
                                "tenant_id": tenant_id,
                                "uid": uid,
                                "trading_date": today,
                                "reason": "budget_usage_store_unavailable",
                                "error": f"{type(e).__name__}: {e}",
                            }
                        )
                    ),
                )
                if not self._budgets_fail_open:
                    return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=checks)
                # Otherwise fall through to local fallback.

        # Fallback enforcement: local in-process usage store.
        usage_key = f"{tenant_id or 'local'}|{agent_id}|{today}"
        with self._budget_usage_lock:
            usage = self._budget_usage_local.get(usage_key) or _AgentBudgetUsage()

            execs_next = int(usage.executions_used) + int(proposed_execs)
            notional_next = float(usage.notional_used_usd) + float(proposed_notional or 0.0)

            # Execution-count cap
            if budget.max_daily_executions is not None and execs_next > int(budget.max_daily_executions):
                cap_check = {
                    "check": "agent_execution_budget",
                    "enabled": True,
                    "cap_hit": "max_daily_executions",
                    "agent_id": agent_id,
                    "tenant_id": tenant_id,
                    "today": today,
                    "executions_used": usage.executions_used,
                    "executions_proposed": proposed_execs,
                    "executions_limit": budget.max_daily_executions,
                }
                checks.append(cap_check)
                logger.warning("exec.agent_budget_cap_hit %s", json.dumps(_to_jsonable(cap_check)))
                return RiskDecision(allowed=False, reason="agent_execution_budget_exceeded", checks=checks)

            # Capital-percent cap
            if (
                budget.max_daily_capital_pct is not None
                and budget.max_daily_capital_pct < 1.0
                and daily_capital is not None
                and daily_capital > 0
            ):
                limit_notional = float(daily_capital) * float(budget.max_daily_capital_pct)
                if notional_next > limit_notional:
                    cap_check = {
                        "check": "agent_execution_budget",
                        "enabled": True,
                        "cap_hit": "max_daily_capital_pct",
                        "agent_id": agent_id,
                        "tenant_id": tenant_id,
                        "today": today,
                        "notional_used_usd": usage.notional_used_usd,
                        "notional_proposed_usd": proposed_notional,
                        "notional_limit_usd": limit_notional,
                        "daily_capital_usd": daily_capital,
                        "max_daily_capital_pct": budget.max_daily_capital_pct,
                    }
                    checks.append(cap_check)
                    logger.warning("exec.agent_budget_cap_hit %s", json.dumps(_to_jsonable(cap_check)))
                    return RiskDecision(allowed=False, reason="agent_execution_budget_exceeded", checks=checks)

            # Allowed => consume locally.
            usage.executions_used = execs_next
            usage.notional_used_usd = notional_next
            self._budget_usage_local[usage_key] = usage

        checks.append(
            {
                "check": "agent_execution_budget",
                "enabled": True,
                "agent_id": agent_id,
                "tenant_id": tenant_id,
                "today": today,
                "executions_used_after": execs_next,
                "notional_used_usd_after": notional_next,
                "max_daily_executions": budget.max_daily_executions,
                "max_daily_capital_pct": budget.max_daily_capital_pct,
            }
        )

        return None

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

        # Hard invariants (crash loud on internal inconsistencies).
        _enforce_risk_invariants_from_intent(intent=intent)

        # Kill switch
        enabled = self.kill_switch_enabled()
        checks.append({"check": "kill_switch", "enabled": enabled})
        if enabled:
            return RiskDecision(allowed=False, reason="kill_switch_enabled", checks=checks)

        # Loss acceleration guard (rolling drawdown velocity)
        # Operates independently of strategy logic: pure risk gate on intent routing.
        try:
            uid = str(intent.metadata.get("uid") or intent.metadata.get("user_id") or os.getenv("EXEC_UID") or "").strip() or None
            guard = LossAccelerationGuard()
            decision = guard.decide(uid=uid)
            m = decision.metrics
            checks.append(
                {
                    "check": "loss_acceleration_guard",
                    "action": decision.action,
                    "reason": decision.reason,
                    "uid": uid,
                    "metrics": (
                        {
                            "window_seconds": m.window_seconds,
                            "points_used": m.points_used,
                            "hwm_equity": m.hwm_equity,
                            "current_equity": m.current_equity,
                            "current_drawdown_pct": m.current_drawdown_pct,
                            "velocity_pct_per_min": m.velocity_pct_per_min,
                            "window_start": m.window_start.isoformat(),
                            "window_end": m.window_end.isoformat(),
                        }
                        if m is not None
                        else None
                    ),
                    "retry_after_seconds": decision.retry_after_seconds,
                    "pause_until": decision.pause_until.isoformat() if decision.pause_until else None,
                }
            )
            if decision.action in {"pause", "throttle"}:
                return RiskDecision(allowed=False, reason=decision.reason or "loss_acceleration", checks=checks)
        except Exception as e:
            # Best-effort: never block if telemetry/reads fail.
            checks.append({"check": "loss_acceleration_guard", "error": str(e)})

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

        # Enforce max_risk_per_trade if provided (soft-fail via rejection),
        # but ALSO treat "allowed=True while exceeding" as a postcondition violation below.
        try:
            md = dict(intent.metadata or {})
            if "max_risk_per_trade" in md and "proposed_trade_risk" in md:
                max_risk_per_trade = _as_money_decimal(md.get("max_risk_per_trade"), name="max_risk_per_trade")
                proposed_trade_risk = _as_money_decimal(md.get("proposed_trade_risk"), name="proposed_trade_risk")
                checks.append(
                    {
                        "check": "max_risk_per_trade",
                        "max_risk_per_trade": float(max_risk_per_trade),
                        "proposed_trade_risk": float(proposed_trade_risk),
                    }
                )
                if proposed_trade_risk > max_risk_per_trade:
                    return RiskDecision(allowed=False, reason="max_risk_per_trade_exceeded", checks=checks)
        except InvariantViolation:
            # If metadata is malformed for risk checking, that's an invariant breach.
            raise
        except Exception as e:
            checks.append({"check": "max_risk_per_trade", "error": str(e)})
            if not self._config.fail_open:
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        # Postcondition (crash loudly if a bypass is possible):
        # If we say "allowed", then max_risk_per_trade MUST be satisfied when provided.
        md = dict(intent.metadata or {})
        if "max_risk_per_trade" in md and "proposed_trade_risk" in md:
            max_risk_per_trade = _as_money_decimal(md.get("max_risk_per_trade"), name="max_risk_per_trade")
            proposed_trade_risk = _as_money_decimal(md.get("proposed_trade_risk"), name="proposed_trade_risk")
            if proposed_trade_risk > max_risk_per_trade:
                _fail_invariant(
                    name="max_risk_per_trade_enforced",
                    message=(
                        f"risk.allowed=True would violate max_risk_per_trade "
                        f"({proposed_trade_risk} > {max_risk_per_trade})"
                    ),
                    context={
                        "max_risk_per_trade": max_risk_per_trade,
                        "proposed_trade_risk": proposed_trade_risk,
                        "symbol": intent.symbol,
                        "strategy_id": intent.strategy_id,
                        "client_intent_id": intent.client_intent_id,
                    },
                )

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
        reservations: ReservationManager | None = None,
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
        self._capital_provider: _FirestoreCapitalProvider | None = None
        self._risk_limits_provider: _FirestoreRiskLimitsProvider | None = None
        # Best-effort, short-lived "in-flight" reservation tracking.
        # Default is NOOP unless a manager is explicitly provided by the runtime.
        self._reservations = BestEffortReservationManager(reservations)

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
            # Best-effort replay marker; never block engine startup.
            logger.exception("exec.replay_startup_marker_failed")
            pass

    @property
    def dry_run(self) -> bool:
        return self._dry_run

    def execute_intent(self, *, intent: OrderIntent) -> ExecutionResult:
        intent = intent.normalized()

        # --- In-flight reservation (best-effort) ---
        # Reserve *during processing only* (not a long-lived open-order hold).
        tenant_id = resolve_tenant_id_from_metadata(intent.metadata)
        reservation: ReservationHandle = NoopReservation()
        try:
            amount_usd = 0.0
            md = dict(intent.metadata or {})
            raw_notional = md.get("notional_usd") or md.get("reserve_usd") or md.get("notional")
            try:
                if raw_notional is not None:
                    amount_usd = float(raw_notional)
            except Exception:
                amount_usd = 0.0
            if amount_usd <= 0 and intent.limit_price is not None and intent.qty > 0:
                try:
                    amount_usd = float(intent.qty) * float(intent.limit_price)
                except Exception:
                    amount_usd = 0.0
            if tenant_id:
                reservation = self._reservations.reserve(
                    tenant_id=tenant_id,
                    broker_account_id=intent.broker_account_id,
                    client_intent_id=intent.client_intent_id,
                    amount_usd=amount_usd,
                    ttl_seconds=300,
                    meta={
                        "symbol": intent.symbol,
                        "side": intent.side,
                        "qty": intent.qty,
                        "asset_class": intent.asset_class,
                    },
                )
        except Exception:
            reservation = NoopReservation()

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

        outcome: str = "unknown"
        release_error: str | None = None
        # NOTE: this is intentionally not a try/except. We want exceptions to
        # propagate (fail-closed), and we rely on explicit critical logging at
        # the point of failure.
        if True:
            # Replay marker (best-effort only)
            try:
                logger.info(
                    "%s",
                    dumps_replay_event(
                        build_replay_event(
                            event="order_intent",
                            component="backend.execution.engine",
                            data={"stage": "received", "intent": audit_ctx},
                            trace_id=trace_id,
                            agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                            run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                        )
                    ),
                )
            except Exception:
                logger.exception("exec.replay_intent_received_log_failed")

            routing_decision: SmartRoutingDecision | None = None
            if self._enable_smart_routing:
                if self._router is None:
                    self._router = SmartRouter()
                routing_decision = self._router.analyze_intent(intent=intent)
                logger.info(
                    "exec.smart_routing %s",
                    json.dumps(
                        _to_jsonable(
                            {
                                "should_execute": routing_decision.should_execute,
                                "reason": routing_decision.reason,
                                "spread_pct": routing_decision.spread_pct,
                                "estimated_slippage": routing_decision.estimated_slippage,
                                "downgraded": routing_decision.downgraded,
                            }
                        )
                    ),
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
                    logger.exception("exec.replay_smart_routing_checkpoint_log_failed")

                if not routing_decision.should_execute:
                    risk = RiskDecision(allowed=False, reason="smart_routing_downgrade")
                    outcome = "downgraded"
                    return ExecutionResult(
                        status="downgraded",
                        risk=risk,
                        routing=routing_decision,
                        message=routing_decision.reason,
                    )

            risk = self._risk.validate(intent=intent)
            corr = risk_correlation_id(
                correlation_id=str(intent.metadata.get("correlation_id") or "").strip() or None
            )
            execution_id = str(intent.metadata.get("execution_id") or intent.client_intent_id or "").strip() or None
            logger.info(
                "exec.risk_decision %s",
                json.dumps(
                    _to_jsonable(
                        {
                            "correlation_id": corr,
                            "execution_id": execution_id,
                            "strategy_id": intent.strategy_id,
                            "risk_decision": "ALLOW" if risk.allowed else "DENY",
                            "allowed": risk.allowed,
                            "reason": risk.reason,
                            "checks": risk.checks,
                        }
                    )
                ),
            )
            # Best-effort: propagate key risk-state for deterministic pre-trade risk guard inputs.
            # This avoids extra DB reads later and keeps the risk guard boundary explicit.
            try:
                for c in list(risk.checks or []):
                    if c.get("check") == "max_daily_trades" and c.get("trades_today") is not None:
                        intent.metadata["_risk_trades_today"] = int(c.get("trades_today"))
                    if c.get("check") == "max_position_size" and c.get("current_qty") is not None:
                        intent.metadata["_risk_current_position_qty"] = float(c.get("current_qty"))
            except Exception:
                pass
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
                                "checks": risk.checks,
                            },
                            trace_id=trace_id,
                            agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                            run_id=str(intent.metadata.get("run_id") or "").strip() or None,
                        )
                    ),
                )
            except Exception:
                logger.exception("exec.replay_risk_checkpoint_log_failed")

            if not risk.allowed:
                outcome = "rejected"
                return ExecutionResult(
                    status="rejected",
                    risk=risk,
                    routing=routing_decision,
                    message=risk.reason,
                )

            if self._dry_run:
                outcome = "dry_run"
                return ExecutionResult(
                    status="dry_run",
                    risk=risk,
                    routing=routing_decision,
                    message="dry_run_enabled",
                )

            # Defense-in-depth: do not place broker orders unless explicitly authorized.
            require_trading_live_mode(action="broker order placement")
            try:
                require_kill_switch_off(operation="broker order placement")
            except ExecutionHaltedError:
                enabled, source = get_kill_switch_state()
                checks = list(risk.checks or [])
                checks.append({"check": "kill_switch", "enabled": bool(enabled), "source": source})
                halted_risk = RiskDecision(allowed=False, reason="kill_switch_enabled", checks=checks)
                outcome = "rejected"
                return ExecutionResult(
                    status="rejected",
                    risk=halted_risk,
                    routing=routing_decision,
                    message="kill_switch_enabled",
                )

        # ---- Idempotency guard (engine-level, replay-safe) ----
        # This prevents duplicate broker submissions if the same intent is processed twice.
        try:
            tenant_id = None
            try:
                # Reuse the ledger's tenant resolution rules (metadata/env).
                tenant_id = _FirestoreLedger()._resolve_tenant_id(intent=intent)  # type: ignore[attr-defined]
            except Exception:
                tenant_id = str(os.getenv("EXEC_TENANT_ID") or os.getenv("TENANT_ID") or "").strip() or None

            if tenant_id:
                from backend.persistence.idempotency_store import FirestoreIdempotencyStore

                idem = FirestoreIdempotencyStore(
                    project_id=os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None
                )
                acquired, rec = idem.begin(
                    tenant_id=tenant_id,
                    scope="execution.broker_place_order",
                    key=str(intent.client_intent_id),
                    payload={"symbol": intent.symbol, "side": intent.side, "qty": intent.qty},
                )
                if not acquired:
                    if rec.outcome and isinstance(rec.outcome.get("broker_order"), dict):
                        broker_order = rec.outcome.get("broker_order")
                        broker_order_id = str(broker_order.get("id") or "").strip() or None
                        return ExecutionResult(
                            status=str(rec.outcome.get("status") or "placed"),
                            risk=risk,
                            routing=routing_decision,
                            broker_order_id=broker_order_id,
                            broker_order=broker_order,
                            message="duplicate_intent_idempotent_return",
                        )
                    return ExecutionResult(
                        status="accepted",
                        risk=risk,
                        routing=routing_decision,
                        message="duplicate_intent_in_progress",
                    )
            else:
                logger.warning("exec.idempotency_disabled missing_tenant_id client_intent_id=%s", intent.client_intent_id)
        except Exception:
            # Idempotency is best-effort; never break safety checks.
            logger.exception("exec.idempotency_guard_failed")

        # ---- Pre-trade assertions (fatal) ----
        # Must run *before* broker placement. Includes deterministic risk guard checks.
        pre = self._assert_pre_trade(intent=intent, trace_id=trace_id)

        broker_order = self._broker.place_order(intent=intent)
        broker_order_id = str(broker_order.get("id") or "").strip() or None
        self._assert_post_trade_order_response(
            intent=intent, broker_order=broker_order, broker_order_id=broker_order_id, trace_id=trace_id
        )
        logger.info(
            "exec.order_placed %s",
            json.dumps(_to_jsonable({"broker": self._broker_name, "broker_order_id": broker_order_id, "order": broker_order})),
        )
        try:
            # Persist idempotency outcome for replay-safe responses.
            _idem = locals().get("idem")
            _tenant_id = locals().get("tenant_id")
            if _idem is not None and _tenant_id:
                _idem.complete(
                    tenant_id=str(_tenant_id),
                    scope="execution.broker_place_order",
                    key=str(intent.client_intent_id),
                    outcome={"status": "placed", "broker_order_id": broker_order_id, "broker_order": broker_order},
                    status="completed",
                )
        except Exception:
            logger.exception("exec.idempotency_complete_failed")
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
            logger.exception("exec.replay_broker_placed_log_failed")
            pass

        # If immediately filled (or partially filled), write to ledger AND portfolio history.
        try:
            status = str(broker_order.get("status") or "").lower()
            filled_qty = float(broker_order.get("filled_qty") or 0.0)
            if status in {"filled", "partially_filled"} or filled_qty > 0:
                self._write_ledger_fill(intent=intent, broker_order=broker_order, fill=broker_order)
                self._write_portfolio_history(intent=intent, broker_order=broker_order, fill=broker_order)
                # If we reserved for this intent, release on first observed fill.
                if reserved and tenant_id_for_reservation and uid_for_reservation:
                    try:
                        release_capital_atomic(
                            tenant_id=tenant_id_for_reservation,
                            uid=uid_for_reservation,
                            broker_account_id=intent.broker_account_id,
                            trade_id=intent.client_intent_id,
                        )
                    except Exception:
                        logger.exception("exec.capital_release_failed (filled)")
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
        # Broker-side action: enforce global authority + kill-switch before side effects.
        require_trading_live_mode(action="broker cancel")
        require_kill_switch_off(operation="broker cancel")
        # --- PAPER TRADING OVERRIDE (START) ---
        # Allow paper trading if TRADING_MODE is 'paper' and Alpaca base URL is paper.
        is_paper_mode = os.getenv("TRADING_MODE", "").strip().lower() == "paper"
        # Accessing _alpaca from self._broker (AlpacaBroker instance) to check base URL
        is_alpaca_paper_url = "paper-api.alpaca.markets" in self._broker._alpaca.trading_base_v2

        if is_paper_mode and is_alpaca_paper_url:
            logger.info(
                "Paper trading enabled: Bypassing fatal_if_execution_reached for execution_engine.cancel "
                "(TRADING_MODE=paper and APCA_API_BASE_URL is paper-api.alpaca.markets)"
            )
        else:
            fatal_if_execution_reached(
                operation="execution_engine.cancel_order",
                explicit_message=(
                    "Runtime execution is forbidden in agent-trader-v2. "
                    "ExecutionEngine.cancel() reached a broker cancel path; aborting."
                ),
                context={"broker_name": self._broker_name, "broker_order_id": str(broker_order_id)},
            )
        # --- PAPER TRADING OVERRIDE (END) ---
        resp = self._broker.cancel_order(broker_order_id=broker_order_id)
        logger.info("exec.cancel_response %s", json.dumps(_to_jsonable(resp)))
        # Best-effort: attempt to release reservation keyed by broker_order_id if caller uses it as trade_id.
        # NOTE: The canonical reservation key is client_intent_id; without it we cannot reliably release here.
        return resp

    def sync_and_ledger_if_filled(self, *, broker_order_id: str) -> dict[str, Any]:
        """
        Poll broker for status; if filled/partially_filled write/update ledger and portfolio history.
        """
        if self._dry_run:
            return {"id": broker_order_id, "status": "dry_run"}

        # --- PAPER TRADING OVERRIDE (START) ---
        # Allow paper trading if TRADING_MODE is 'paper' and Alpaca base URL is paper.
        is_paper_mode = os.getenv("TRADING_MODE", "").strip().lower() == "paper"
        # Accessing _alpaca from self._broker (AlpacaBroker instance) to check base URL
        is_alpaca_paper_url = "paper-api.alpaca.markets" in self._broker._alpaca.trading_base_v2

        if is_paper_mode and is_alpaca_paper_url:
            logger.info(
                "Paper trading enabled: Bypassing fatal_if_execution_reached for execution_engine.sync_and_ledger_if_filled "
                "(TRADING_MODE=paper and APCA_API_BASE_URL is paper-api.alpaca.markets)"
            )
        else:
            fatal_if_execution_reached(
                operation="execution_engine.get_order_status",
                explicit_message=(
                    "Runtime execution is forbidden in agent-trader-v2. "
                    "ExecutionEngine.sync_and_ledger_if_filled() reached a broker status poll; aborting."
                ),
                context={"broker_name": self._broker_name, "broker_order_id": str(broker_order_id)},
            )
        # --- PAPER TRADING OVERRIDE (END) ---
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
            # Best-effort: release reservation if client_intent_id matches reservation trade_id.
            try:
                if self._ledger is None:
                    self._ledger = _FirestoreLedger()
                tenant_id = self._ledger._resolve_tenant_id(intent=intent)  # type: ignore[attr-defined]
                uid = self._ledger._resolve_uid(intent=intent)  # type: ignore[attr-defined]
                release_capital_atomic(
                    tenant_id=tenant_id,
                    uid=uid,
                    broker_account_id=intent.broker_account_id,
                    trade_id=intent.client_intent_id,
                )
            except Exception:
                logger.exception("exec.capital_release_failed (sync)")
        return order

    @dataclass(frozen=True, slots=True)
    class _PreTradeState:
        """
        Captures what we validated pre-trade so post-trade reconciliation can be based
        on the *actual fill* without relying on asynchronous account snapshot updates.
        """

        capital: _CapitalSnapshot
        estimated_price: float
        estimated_notional: float
        capital_available: float
        marketdata: dict[str, Any]

    def _critical(self, event: str, *, payload: dict[str, Any]) -> None:
        # Ensure CRITICAL logging cannot crash the process.
        try:
            logger.critical("%s %s", event, json.dumps(_to_jsonable(payload)))
        except Exception:
            logger.critical("%s (payload_unserializable)", event)

    def _env_float(self, name: str, default: float | None = None) -> float | None:
        v = os.getenv(name)
        if v is None or str(v).strip() == "":
            return default
        return float(v)

    def _env_int(self, name: str, default: int) -> int:
        v = os.getenv(name)
        if v is None or str(v).strip() == "":
            return int(default)
        return int(v)

    def _market_quote_strict(self, *, intent: OrderIntent) -> dict[str, Any]:
        provider = MarketDataProvider()
        quote = provider.get_quote(symbol=intent.symbol, asset_class=intent.asset_class)
        if quote.get("error"):
            raise PreTradeAssertionError(f"marketdata_quote_unavailable error={quote.get('error')}")
        mid = float(quote.get("mid_price") or 0.0)
        bid = float(quote.get("bid") or 0.0)
        ask = float(quote.get("ask") or 0.0)
        if mid <= 0.0 and bid <= 0.0 and ask <= 0.0:
            raise PreTradeAssertionError("marketdata_quote_invalid_zero_prices")
        return quote

    def _assert_pre_trade(self, *, intent: OrderIntent, trace_id: str | None) -> _PreTradeState:
        """
        Pre-trade assertions (fatal).

        Requirements:
        - capital available
        - risk bounds (notional bounds beyond RiskManager structural checks)
        - data freshness
        """
        # ---- Data freshness (market ingest heartbeat) ----
        stale_s = self._env_int("MARKETDATA_STALE_THRESHOLD_S", 120)
        tenant_id = str(intent.metadata.get("tenant_id") or os.getenv("EXEC_TENANT_ID") or "").strip() or None
        from backend.execution.marketdata_health import check_market_ingest_heartbeat

        hb = check_market_ingest_heartbeat(tenant_id=tenant_id, stale_threshold_seconds=stale_s)
        if hb.is_stale:
            payload = {
                "reason": "marketdata_stale",
                "tenant_id": tenant_id,
                "heartbeat": _to_jsonable(hb),
                "intent": _to_jsonable(intent),
                "trace_id": trace_id,
            }
            self._critical("exec.pretrade_assertion_failed", payload=payload)
            raise PreTradeAssertionError("marketdata_stale")

        # ---- Market quote + quote freshness (per-symbol) ----
        quote = self._market_quote_strict(intent=intent)
        quote_ts = None
        if quote.get("timestamp") is not None:
            try:
                quote_ts = parse_ts(quote.get("timestamp"))
            except Exception:
                quote_ts = None
        freshness = check_freshness(
            latest_ts=quote_ts,
            stale_after=timedelta(seconds=float(stale_s)),
            source="execution_engine.market_quote",
        )
        if not freshness.ok:
            payload = {
                "reason": "quote_not_fresh",
                "freshness": _to_jsonable(freshness),
                "quote": _to_jsonable(quote),
                "intent": _to_jsonable(intent),
                "trace_id": trace_id,
            }
            self._critical("exec.pretrade_assertion_failed", payload=payload)
            raise PreTradeAssertionError(f"quote_not_fresh:{freshness.reason_code}")

        # ---- Price + notional estimation ----
        est_price = None
        if intent.order_type == "limit":
            if intent.limit_price is None or float(intent.limit_price) <= 0:
                raise PreTradeAssertionError("limit_order_missing_or_invalid_limit_price")
            est_price = float(intent.limit_price)
        else:
            meta_price = intent.metadata.get("expected_price")
            if meta_price is not None:
                try:
                    est_price = float(meta_price)
                except Exception as e:
                    raise PreTradeAssertionError(f"expected_price_invalid:{e}") from e
            if est_price is None or est_price <= 0:
                est_price = float(quote.get("mid_price") or 0.0) or float(quote.get("ask") or 0.0) or float(quote.get("bid") or 0.0)
        if est_price is None or est_price <= 0:
            raise PreTradeAssertionError("unable_to_estimate_price")

        est_notional = float(intent.qty) * float(est_price)
        if est_notional <= 0:
            raise PreTradeAssertionError("estimated_notional_non_positive")

        # ---- Capital snapshot ----
        if self._capital_provider is None:
            self._capital_provider = _FirestoreCapitalProvider()
        cap = self._capital_provider.get_capital_snapshot(intent=intent)

        # Capital snapshot freshness (avoid trading on stale account balance)
        cap_stale_s = self._env_int("ACCOUNT_SNAPSHOT_STALE_THRESHOLD_S", 120)
        cap_fresh = check_freshness(
            latest_ts=cap.updated_at_utc,
            stale_after=timedelta(seconds=float(cap_stale_s)),
            source=f"firestore:{cap.source_path}",
        )
        if not cap_fresh.ok:
            payload = {
                "reason": "capital_snapshot_not_fresh",
                "capital": _to_jsonable(cap),
                "freshness": _to_jsonable(cap_fresh),
                "intent": _to_jsonable(intent),
                "trace_id": trace_id,
            }
            self._critical("exec.pretrade_assertion_failed", payload=payload)
            raise PreTradeAssertionError(f"capital_snapshot_not_fresh:{cap_fresh.reason_code}")

        # Prefer buying_power; fall back to cash if buying_power is missing/zero.
        available = float(cap.buying_power) if float(cap.buying_power) > 0 else float(cap.cash)
        if available < 0:
            raise PreTradeAssertionError("capital_available_negative")

        # ---- Risk Guard (deterministic tool boundary) ----
        # Enforces: max daily loss, max order notional, max trades/day, max per-symbol exposure.
        # Inputs are strict/explicit; missing required state fails closed (when limits are enabled).
        try:
            # Baseline (env) limits (existing behavior).
            max_daily_loss_env = self._env_float("EXEC_MAX_DAILY_LOSS_USD", None)
            max_order_notional = self._env_float("EXEC_MAX_ORDER_NOTIONAL", None)
            max_trades_per_day = _as_int_or_none(os.getenv("EXEC_MAX_DAILY_TRADES"))
            max_per_symbol_exposure_env = self._env_float("EXEC_MAX_PER_SYMBOL_EXPOSURE_USD", None)

            # Provided by earlier risk validation when available (see execute_intent()).
            trades_today = _as_int_or_none(intent.metadata.get("_risk_trades_today"))
            current_qty = _as_float_or_none(intent.metadata.get("_risk_current_position_qty"))

            # Daily PnL is expected from upstream deterministic workflow/ledger computation.
            daily_pnl = _as_float_or_none(
                intent.metadata.get("daily_pnl_usd")
                if intent.metadata.get("daily_pnl_usd") is not None
                else (
                    -abs(_as_float_or_none(intent.metadata.get("daily_loss_usd")) or 0.0)
                    if intent.metadata.get("daily_loss_usd") is not None
                    else None
                )
            )

            corr = risk_correlation_id(
                correlation_id=str(intent.metadata.get("correlation_id") or trace_id or "").strip() or None
            )
            execution_id = str(intent.metadata.get("execution_id") or intent.client_intent_id or "").strip() or None

            decision = evaluate_risk_guard(
                trade=RiskGuardTrade(
                    symbol=intent.symbol,
                    side=intent.side,
                    qty=float(intent.qty),
                    estimated_price_usd=float(est_price),
                    estimated_notional_usd=float(est_notional),
                ),
                state=RiskGuardState(
                    trading_date=_iso_date_utc(),
                    daily_pnl_usd=daily_pnl,
                    trades_today=trades_today,
                    current_position_qty=current_qty,
                    correlation_id=corr,
                    execution_id=execution_id,
                    strategy_id=intent.strategy_id,
                ),
                limits=RiskGuardLimits(
                    max_daily_loss_usd=max_daily_loss,
                    max_order_notional_usd=max_order_notional,
                    max_trades_per_day=max_trades_per_day,
                    max_per_symbol_exposure_usd=max_per_symbol_exposure,
                ),
            )
            logger.info(
                "exec.risk_guard_decision %s",
                json.dumps(
                    _to_jsonable(
                        {
                            "correlation_id": corr,
                            "execution_id": execution_id,
                            "strategy_id": intent.strategy_id,
                            "risk_decision": "ALLOW" if decision.allowed else "DENY",
                        }
                    )
                ),
            )
            if not decision.allowed:
                payload = {
                    "reason": "risk_guard_blocked",
                    "correlation_id": corr,
                    "execution_id": execution_id,
                    "strategy_id": intent.strategy_id,
                    "risk_decision": "DENY",
                    "risk_guard": decision.to_dict(),
                    "intent": _to_jsonable(intent),
                    "trace_id": trace_id,
                }
                self._critical("exec.pretrade_assertion_failed", payload=payload)
                raise PreTradeAssertionError("risk_guard_blocked")
        except PreTradeAssertionError:
            raise
        except Exception as e:
            payload = {
                "reason": "risk_guard_error",
                "error_type": type(e).__name__,
                "intent": _to_jsonable(intent),
                "trace_id": trace_id,
            }
            self._critical("exec.pretrade_assertion_failed", payload=payload)
            raise PreTradeAssertionError("risk_guard_error")

        max_notional_pct = self._env_float("EXEC_MAX_ORDER_NOTIONAL_PCT_EQUITY", None)
        if max_notional_pct is not None and float(cap.equity) > 0:
            limit = float(cap.equity) * float(max_notional_pct)
            if est_notional > limit:
                payload = {
                    "reason": "risk_max_order_notional_pct_equity_exceeded",
                    "estimated_notional": est_notional,
                    "equity": float(cap.equity),
                    "pct_limit": float(max_notional_pct),
                    "limit": limit,
                    "intent": _to_jsonable(intent),
                    "trace_id": trace_id,
                }
                self._critical("exec.pretrade_assertion_failed", payload=payload)
                raise PreTradeAssertionError("risk_max_order_notional_pct_equity_exceeded")

        # ---- Capital available (buy-side) ----
        # For sells we don't enforce buying power here; position-level constraints live in RiskManager.
        if intent.side == "buy":
            # Buffer covers typical slippage + fees.
            fee_bps = float(self._env_float("EXEC_FEE_BPS_BUFFER", 5.0) or 5.0)  # 5 bps default
            slip = float(intent.estimated_slippage or float(quote.get("spread_pct") or 0.0) or 0.0)
            buffer_mult = 1.0 + max(0.0, slip) + (max(0.0, fee_bps) / 10000.0)
            required = est_notional * buffer_mult
            if available + 1e-6 < required:
                payload = {
                    "reason": "insufficient_capital",
                    "available": available,
                    "required": required,
                    "estimated_notional": est_notional,
                    "buffer_mult": buffer_mult,
                    "capital": _to_jsonable(cap),
                    "quote": _to_jsonable(quote),
                    "intent": _to_jsonable(intent),
                    "trace_id": trace_id,
                }
                self._critical("exec.pretrade_assertion_failed", payload=payload)
                raise PreTradeAssertionError("insufficient_capital")

        return ExecutionEngine._PreTradeState(
            capital=cap,
            estimated_price=float(est_price),
            estimated_notional=float(est_notional),
            capital_available=float(available),
            marketdata=dict(quote),
        )

    def _assert_post_trade_order_response(
        self,
        *,
        intent: OrderIntent,
        broker_order: dict[str, Any],
        broker_order_id: str | None,
        trace_id: str | None,
    ) -> None:
        """
        Post-trade assertions immediately after submission.

        Requirements:
        - expected fill state / order lifecycle state is sane
        """
        status = str(broker_order.get("status") or "").strip().lower()
        # Alpaca statuses vary; allow the common "new/accepted/pending_*" set.
        allowed = {
            "new",
            "accepted",
            "pending_new",
            "partially_filled",
            "filled",
            "replaced",
            "pending_replace",
            "pending_cancel",
        }
        if not broker_order_id:
            payload = {"reason": "broker_order_missing_id", "order": _to_jsonable(broker_order), "intent": _to_jsonable(intent), "trace_id": trace_id}
            self._critical("exec.posttrade_assertion_failed", payload=payload)
            raise PostTradeAssertionError("broker_order_missing_id")
        if not status or status not in allowed:
            payload = {
                "reason": "unexpected_broker_order_status",
                "status": status,
                "allowed": sorted(allowed),
                "broker_order_id": broker_order_id,
                "order": _to_jsonable(broker_order),
                "intent": _to_jsonable(intent),
                "trace_id": trace_id,
            }
            self._critical("exec.posttrade_assertion_failed", payload=payload)
            # Best-effort safe abort (cancel) for unknown/invalid statuses.
            self._safe_abort_cancel(broker_order_id=broker_order_id, trace_id=trace_id)
            raise PostTradeAssertionError(f"unexpected_broker_order_status:{status or 'missing'}")

        client_id = str(broker_order.get("client_order_id") or "").strip()
        if client_id and client_id != intent.client_intent_id:
            payload = {
                "reason": "client_order_id_mismatch",
                "expected": intent.client_intent_id,
                "actual": client_id,
                "broker_order_id": broker_order_id,
                "trace_id": trace_id,
            }
            self._critical("exec.posttrade_assertion_failed", payload=payload)
            self._safe_abort_cancel(broker_order_id=broker_order_id, trace_id=trace_id)
            raise PostTradeAssertionError("client_order_id_mismatch")

    def _assert_post_trade_fill_and_reconcile(
        self,
        *,
        intent: OrderIntent,
        broker_order: dict[str, Any],
        broker_order_id: str | None,
        pre: _PreTradeState,
        trace_id: str | None,
    ) -> None:
        """
        Post-trade assertions on immediate fills.

        Requirements:
        - expected fill state (filled/partial implies usable fill qty/price)
        - capital reconciliation (actual fill notional must fit within pre-trade capital snapshot)
        """
        status = str(broker_order.get("status") or "").strip().lower()
        filled_qty = float(broker_order.get("filled_qty") or 0.0)
        filled_avg_price = broker_order.get("filled_avg_price")
        if status not in {"filled", "partially_filled"} and filled_qty <= 0:
            payload = {
                "reason": "fill_expected_but_missing",
                "status": status,
                "filled_qty": filled_qty,
                "broker_order_id": broker_order_id,
                "order": _to_jsonable(broker_order),
                "trace_id": trace_id,
            }
            self._critical("exec.posttrade_assertion_failed", payload=payload)
            self._safe_abort_cancel(broker_order_id=broker_order_id, trace_id=trace_id)
            raise PostTradeAssertionError("fill_expected_but_missing")
        if filled_qty <= 0:
            raise PostTradeAssertionError("filled_qty_non_positive")
        if filled_avg_price is None:
            raise PostTradeAssertionError("filled_avg_price_missing")
        fill_px = float(filled_avg_price)
        if fill_px <= 0:
            raise PostTradeAssertionError("filled_avg_price_non_positive")

        fill_notional = float(filled_qty) * float(fill_px)
        if fill_notional <= 0:
            raise PostTradeAssertionError("fill_notional_non_positive")

        # Capital reconciliation against the same snapshot we used to authorize.
        if intent.side == "buy":
            # If we somehow filled for more notional than we authorized, that's a critical failure.
            # Use a tolerance (fees/slippage) so tiny differences don't fail.
            tolerance = float(self._env_float("EXEC_POSTTRADE_RECONCILE_TOLERANCE_PCT", 0.02) or 0.02)  # 2%
            allowed = float(pre.capital_available) * (1.0 + max(0.0, tolerance))
            if fill_notional > allowed + 1e-6:
                payload = {
                    "reason": "fill_exceeds_pretrade_capital",
                    "fill_notional": fill_notional,
                    "capital_available": float(pre.capital_available),
                    "allowed_with_tolerance": allowed,
                    "tolerance_pct": tolerance,
                    "pre": _to_jsonable(pre),
                    "broker_order_id": broker_order_id,
                    "trace_id": trace_id,
                }
                self._critical("exec.posttrade_assertion_failed", payload=payload)
                raise PostTradeAssertionError("fill_exceeds_pretrade_capital")

    def _safe_abort_cancel(self, *, broker_order_id: str | None, trace_id: str | None) -> None:
        """
        Best-effort safe abort: cancel the broker order.

        - Never retries blindly.
        - Never swallows: cancellation errors are logged CRITICAL but not raised here,
          because the *primary* exception should propagate.
        """
        if not broker_order_id:
            return
        try:
            # In this repo, runtime cancel may be forbidden; keep the safety boundary.
            self.cancel(broker_order_id=broker_order_id)
        except Exception as e:
            self._critical(
                "exec.safe_abort_cancel_failed",
                payload={"broker_order_id": broker_order_id, "trace_id": trace_id, "error": f"{type(e).__name__}: {e}"},
            )

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
        doc_ref = (
            db.collection("users")
            .document(uid)
            .collection("portfolio")
            .document("history")
            .collection("trades")
            .document(history_id)
        )
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
            
            # Create a deterministic history id so reprocessing does not duplicate entries.
            # Note: we intentionally include filled fields to separate partial fills.
            filled_at_key = (
                filled_at_raw.astimezone(timezone.utc).isoformat()
                if isinstance(filled_at_raw, datetime)
                else str(filled_at_raw or "")
            )
            fp = f"{broker_order_id}|{filled_qty}|{filled_avg_price}|{filled_at_key}|{intent.symbol}|{intent.side}"
            history_id = hashlib.sha1(fp.encode("utf-8")).hexdigest()
            
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
            # Idempotent write (same doc id + overwrite/merge).
            doc_ref.set(history_entry, merge=True)
            
            logger.info(
                "exec.portfolio_history_written uid=%s symbol=%s qty=%s price=%s",
                uid, intent.symbol, filled_qty, filled_avg_price
            )
            
        except Exception as e:
            self._critical(
                "exec.portfolio_history_write_failed",
                payload={
                    "uid": uid,
                    "symbol": intent.symbol,
                    "broker_order_id": broker_order_id,
                    "error": f"{type(e).__name__}: {e}",
                },
            )
            raise

        logger.info(
            "exec.portfolio_history_written uid=%s symbol=%s qty=%s price=%s",
            uid, intent.symbol, filled_qty, filled_avg_price
        )

