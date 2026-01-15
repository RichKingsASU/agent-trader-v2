"""
Execution engine (intents -> risk checks -> broker routing).

This module is intentionally dependency-light so unit tests can validate
safety invariants without live APIs or external services.

Core safety contract:
- Strategies must emit order *intents* only.
- Broker-side order placement MUST be explicitly enabled at runtime.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, runtime_checkable
from urllib.parse import urlparse

from backend.common.agent_mode import require_live_mode
from backend.common.execution_enabled import require_execution_enabled
from backend.common.kill_switch import get_kill_switch_state
from backend.common.runtime_execution_prevention import fatal_if_execution_reached

logger = logging.getLogger(__name__)


# -----------------------------
# Data contracts
# -----------------------------


@dataclass(frozen=True)
class OrderIntent:
    strategy_id: str
    broker_account_id: str
    symbol: str
    side: str
    qty: float

    order_type: str = "market"
    time_in_force: Optional[str] = "day"
    limit_price: Optional[float] = None

    client_intent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Multi-asset extensions (safe defaults).
    asset_class: str = "EQUITY"
    estimated_slippage: Optional[float] = None

    def normalized(self) -> "OrderIntent":
        # Normalization hook for future symbol conventions. Keep stable for tests.
        return self


@dataclass(frozen=True)
class RiskConfig:
    max_position_qty: float = 100.0
    max_daily_trades: int = 50
    fail_open: bool = False


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    checks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class SmartRoutingDecision:
    should_execute: bool
    reason: str
    estimated_slippage: Optional[float] = None
    spread_pct: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    downgraded: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    risk: RiskDecision
    broker_order_id: Optional[str] = None
    broker_order: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    routing: Optional[SmartRoutingDecision] = None


# -----------------------------
# Interfaces
# -----------------------------


@runtime_checkable
class Broker(Protocol):
    def place_order(self, *, intent: OrderIntent) -> Dict[str, Any]: ...

    def cancel_order(self, *, broker_order_id: str) -> Dict[str, Any]: ...

    def get_order_status(self, *, broker_order_id: str) -> Dict[str, Any]: ...


@runtime_checkable
class MarketDataProvider(Protocol):
    def get_quote(self, *, symbol: str) -> Dict[str, Any]: ...


# -----------------------------
# Smart router (optional)
# -----------------------------


class SmartRouter:
    def __init__(self, *, market_data_provider: MarketDataProvider | None = None, max_spread_pct: float = 0.001) -> None:
        self._provider = market_data_provider
        self._max_spread_pct = float(max_spread_pct)

    def analyze_intent(self, *, intent: OrderIntent) -> SmartRoutingDecision:
        # Use pre-computed slippage if provided by the strategy.
        if intent.estimated_slippage is not None:
            est = float(intent.estimated_slippage)
            if est > self._max_spread_pct:
                return SmartRoutingDecision(
                    should_execute=False,
                    reason=f"Estimated slippage {est:.4%} exceeds threshold {self._max_spread_pct:.4%}",
                    estimated_slippage=est,
                    spread_pct=est,
                    downgraded=True,
                )
            return SmartRoutingDecision(
                should_execute=True,
                reason="Estimated slippage within acceptable range",
                estimated_slippage=est,
                spread_pct=est,
                downgraded=False,
            )

        # Otherwise, try to derive spread from market data.
        if self._provider is None:
            return SmartRoutingDecision(should_execute=True, reason="No market data provider configured; allow", downgraded=False)

        q = self._provider.get_quote(symbol=intent.symbol)
        bid = float(q.get("bid") or 0.0)
        ask = float(q.get("ask") or 0.0)
        mid = float(q.get("mid_price") or ((bid + ask) / 2.0 if bid and ask else 0.0))
        spread = float(q.get("spread") or (ask - bid))
        spread_pct = float(q.get("spread_pct") or (spread / mid if mid else 0.0))

        if spread_pct > self._max_spread_pct:
            return SmartRoutingDecision(
                should_execute=False,
                reason=f"Spread {spread_pct:.2%} exceeds threshold {self._max_spread_pct:.2%}",
                estimated_slippage=spread_pct,
                spread_pct=spread_pct,
                bid=bid,
                ask=ask,
                downgraded=True,
            )
        return SmartRoutingDecision(
            should_execute=True,
            reason="Spread within acceptable range",
            estimated_slippage=spread_pct,
            spread_pct=spread_pct,
            bid=bid,
            ask=ask,
            downgraded=False,
        )


# -----------------------------
# Risk management
# -----------------------------


class RiskManager:
    def __init__(self, *, config: RiskConfig | None = None, ledger: Any | None = None, positions: Any | None = None) -> None:
        self.config = config or RiskConfig()
        self.ledger = ledger
        self.positions = positions

    def validate(self, *, intent: OrderIntent) -> RiskDecision:
        checks: list[dict[str, Any]] = []

        enabled, source = get_kill_switch_state()
        if enabled:
            checks.append({"check": "kill_switch", "enabled": True, "source": source})
            return RiskDecision(allowed=False, reason="kill_switch_enabled", checks=checks)
        checks.append({"check": "kill_switch", "enabled": False})

        # Max daily trades.
        try:
            if self.ledger is None:
                raise RuntimeError("ledger_unconfigured")
            trading_date = datetime.now(timezone.utc).date().isoformat()
            trades_today = int(self.ledger.count_trades_today(broker_account_id=intent.broker_account_id, trading_date=trading_date))
            checks.append({"check": "max_daily_trades", "trades_today": trades_today, "limit": int(self.config.max_daily_trades)})
            if trades_today >= int(self.config.max_daily_trades):
                return RiskDecision(allowed=False, reason="max_daily_trades_exceeded", checks=checks)
        except Exception as e:
            checks.append({"check": "max_daily_trades", "error": str(e)})
            if not bool(self.config.fail_open):
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        # Max position size.
        try:
            if self.positions is None:
                raise RuntimeError("positions_unconfigured")
            current_qty = float(self.positions.get_position_qty(symbol=intent.symbol))
            delta = float(intent.qty) if str(intent.side).lower() == "buy" else -float(intent.qty)
            projected = current_qty + delta
            limit_abs = float(self.config.max_position_qty)
            checks.append(
                {
                    "check": "max_position_size",
                    "current_qty": current_qty,
                    "delta_qty": delta,
                    "projected_qty": projected,
                    "limit_abs_qty": limit_abs,
                }
            )
            if abs(projected) > limit_abs:
                return RiskDecision(allowed=False, reason="max_position_size_exceeded", checks=checks)
        except Exception as e:
            checks.append({"check": "max_position_size", "error": str(e)})
            if not bool(self.config.fail_open):
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        return RiskDecision(allowed=True, reason="ok", checks=checks)


# -----------------------------
# Brokers
# -----------------------------


@dataclass
class _ApcaEnv:
    api_key_id: str
    api_secret_key: str
    api_base_url: str


def _is_truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_base_url(url: str) -> str:
    u = str(url).strip()
    return u[:-1] if u.endswith("/") else u


def _assert_paper_only_base_url_or_fatal(*, base_url: str, trading_mode: str, operation: str) -> None:
    """
    Runtime safety boundary: in TRADING_MODE=paper, live trading host must be unreachable.
    Also refuse attempting to use paper endpoints when TRADING_MODE != paper.
    """
    tm = str(trading_mode or "").strip().lower()
    base = _normalize_base_url(base_url)
    host = (urlparse(base).hostname or "").lower()
    if tm != "paper":
        fatal_if_execution_reached(
            operation=operation,
            explicit_message=f"REFUSED: broker execution forbidden unless TRADING_MODE='paper' (got {tm!r})",
            context={"trading_mode": tm, "base_url": base},
        )
    if host != "paper-api.alpaca.markets":
        fatal_if_execution_reached(
            operation=operation,
            explicit_message=f"REFUSED: live Alpaca host forbidden in paper mode (got {base!r})",
            context={"trading_mode": tm, "base_url": base, "host": host},
        )


class AlpacaBroker:
    """
    Minimal Alpaca Trading v2 REST broker.

    Safety:
    - Must pass the `EXECUTION_ENABLED` runtime gate before any broker request.
    - Must be paper-only when TRADING_MODE=paper; will hard-fail on live base URLs.
    """

    def __init__(self, *, request_timeout_s: float = 15.0) -> None:
        self.request_timeout_s = float(request_timeout_s)
        self._alpaca = _ApcaEnv(
            api_key_id=str(os.getenv("APCA_API_KEY_ID") or "").strip(),
            api_secret_key=str(os.getenv("APCA_API_SECRET_KEY") or "").strip(),
            api_base_url=_normalize_base_url(os.getenv("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"),
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "APCA-API-KEY-ID": self._alpaca.api_key_id,
            "APCA-API-SECRET-KEY": self._alpaca.api_secret_key,
        }

    def place_order(self, *, intent: OrderIntent) -> Dict[str, Any]:
        require_execution_enabled(operation="alpaca.place_order", context={"symbol": intent.symbol, "side": intent.side, "qty": intent.qty})
        _assert_paper_only_base_url_or_fatal(
            base_url=self._alpaca.api_base_url,
            trading_mode=os.getenv("TRADING_MODE", "paper"),
            operation="alpaca.place_order",
        )
        # Enforce the repo's authority boundary: only LIVE mode may attempt broker placement.
        require_live_mode(action="place_order")

        try:
            import requests  # local import: keep unit tests lightweight
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"requests dependency missing: {e}") from e

        url = f"{self._alpaca.api_base_url}/v2/orders"
        payload: Dict[str, Any] = {
            "symbol": intent.symbol,
            "side": str(intent.side).lower(),
            "type": intent.order_type,
            "qty": intent.qty,
            "time_in_force": intent.time_in_force or "day",
        }
        if intent.limit_price is not None:
            payload["limit_price"] = intent.limit_price
        if intent.client_intent_id:
            payload["client_order_id"] = intent.client_intent_id
        r = requests.post(url, headers=self._headers(), json=payload, timeout=self.request_timeout_s)
        r.raise_for_status()
        return dict(r.json() or {})

    def cancel_order(self, *, broker_order_id: str) -> Dict[str, Any]:
        require_execution_enabled(operation="alpaca.cancel_order", context={"broker_order_id": broker_order_id})
        _assert_paper_only_base_url_or_fatal(
            base_url=self._alpaca.api_base_url,
            trading_mode=os.getenv("TRADING_MODE", "paper"),
            operation="alpaca.cancel_order",
        )
        require_live_mode(action="cancel_order")
        try:
            import requests
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"requests dependency missing: {e}") from e
        url = f"{self._alpaca.api_base_url}/v2/orders/{broker_order_id}"
        r = requests.delete(url, headers=self._headers(), timeout=self.request_timeout_s)
        r.raise_for_status()
        return dict(r.json() or {})

    def get_order_status(self, *, broker_order_id: str) -> Dict[str, Any]:
        require_execution_enabled(operation="alpaca.get_order_status", context={"broker_order_id": broker_order_id})
        _assert_paper_only_base_url_or_fatal(
            base_url=self._alpaca.api_base_url,
            trading_mode=os.getenv("TRADING_MODE", "paper"),
            operation="alpaca.get_order_status",
        )
        require_live_mode(action="get_order_status")
        try:
            import requests
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"requests dependency missing: {e}") from e
        url = f"{self._alpaca.api_base_url}/v2/orders/{broker_order_id}"
        r = requests.get(url, headers=self._headers(), timeout=self.request_timeout_s)
        r.raise_for_status()
        return dict(r.json() or {})


class DryRunBroker:
    """
    Broker that never routes orders.
    """

    def place_order(self, *, intent: OrderIntent) -> Dict[str, Any]:  # noqa: ARG002
        return {"id": None, "status": "dry_run"}

    def cancel_order(self, *, broker_order_id: str) -> Dict[str, Any]:  # noqa: ARG002
        return {"id": broker_order_id, "status": "dry_run"}

    def get_order_status(self, *, broker_order_id: str) -> Dict[str, Any]:  # noqa: ARG002
        return {"id": broker_order_id, "status": "dry_run"}


# -----------------------------
# Execution engine orchestration
# -----------------------------


class _AgentBudgetState:
    def __init__(self) -> None:
        self.executions_by_strategy: Dict[str, int] = {}
        self.notional_by_strategy: Dict[str, float] = {}


class ExecutionEngine:
    def __init__(
        self,
        *,
        broker: Broker,
        risk: RiskManager | None = None,
        dry_run: bool = True,
        broker_name: str = "alpaca",
        router: SmartRouter | None = None,
        enable_smart_routing: bool = False,
        reservations: Any | None = None,
    ) -> None:
        self._broker = broker
        self.broker_name = str(broker_name)
        self.dry_run = bool(dry_run)
        self.risk = risk or RiskManager(config=RiskConfig(fail_open=True), ledger=None, positions=None)
        self.router = router or SmartRouter()
        self.enable_smart_routing = bool(enable_smart_routing)
        self._reservations = reservations
        self._budget_state = _AgentBudgetState()

    # --- Agent execution budgets (in-memory; used for unit-testable safety caps) ---
    def _budgets_config(self) -> Dict[str, Any] | None:
        if not _is_truthy(os.getenv("EXEC_AGENT_BUDGETS_ENABLED")):
            return None
        raw = str(os.getenv("EXEC_AGENT_BUDGETS_JSON") or "").strip()
        if not raw:
            return {}
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def _check_and_record_budgets(self, *, intent: OrderIntent) -> RiskDecision | None:
        cfg = self._budgets_config()
        if cfg is None:
            return None
        rule = cfg.get(intent.strategy_id) if isinstance(cfg, dict) else None
        if not isinstance(rule, dict):
            return None

        max_exec = rule.get("max_daily_executions")
        max_cap_pct = rule.get("max_daily_capital_pct")

        # Execution-count cap.
        if max_exec is not None:
            try:
                limit = int(max_exec)
                used = int(self._budget_state.executions_by_strategy.get(intent.strategy_id, 0))
                if used >= limit:
                    return RiskDecision(allowed=False, reason="agent_execution_budget_exceeded", checks=[{"check": "agent_budget.max_daily_executions", "used": used, "limit": limit}])
            except Exception:
                return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=[{"check": "agent_budget.max_daily_executions", "error": "invalid_config"}])

        # Capital-percent cap (requires daily_capital_usd + notional_usd).
        if max_cap_pct is not None:
            try:
                limit_pct = float(max_cap_pct)
                meta = intent.metadata or {}
                daily_capital = meta.get("daily_capital_usd")
                notional = meta.get("notional_usd")
                if daily_capital is None or notional is None:
                    return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=[{"check": "agent_budget.max_daily_capital_pct", "error": "missing_daily_capital_or_notional"}])
                daily_capital_f = float(daily_capital)
                notional_f = float(notional)
                used = float(self._budget_state.notional_by_strategy.get(intent.strategy_id, 0.0))
                if (used + notional_f) > (daily_capital_f * limit_pct):
                    return RiskDecision(
                        allowed=False,
                        reason="agent_execution_budget_exceeded",
                        checks=[
                            {
                                "check": "agent_budget.max_daily_capital_pct",
                                "used_notional": used,
                                "new_notional": notional_f,
                                "daily_capital_usd": daily_capital_f,
                                "limit_pct": limit_pct,
                            }
                        ],
                    )
            except Exception:
                return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=[{"check": "agent_budget.max_daily_capital_pct", "error": "invalid_state"}])

        return None

    def _record_budget_use(self, *, intent: OrderIntent) -> None:
        cfg = self._budgets_config()
        if cfg is None:
            return
        rule = cfg.get(intent.strategy_id) if isinstance(cfg, dict) else None
        if not isinstance(rule, dict):
            return

        if rule.get("max_daily_executions") is not None:
            self._budget_state.executions_by_strategy[intent.strategy_id] = int(self._budget_state.executions_by_strategy.get(intent.strategy_id, 0)) + 1

        if rule.get("max_daily_capital_pct") is not None:
            meta = intent.metadata or {}
            notional = meta.get("notional_usd")
            if notional is None:
                return
            self._budget_state.notional_by_strategy[intent.strategy_id] = float(self._budget_state.notional_by_strategy.get(intent.strategy_id, 0.0)) + float(notional)

    # --- Paper URL guard (secondary defense used by tests/mocks) ---
    def _enforce_paper_only_if_possible(self, *, operation: str) -> None:
        broker = getattr(self, "_broker", None)
        alp = getattr(broker, "_alpaca", None)
        base_url = getattr(alp, "api_base_url", None) if alp is not None else None
        if base_url:
            _assert_paper_only_base_url_or_fatal(base_url=str(base_url), trading_mode=os.getenv("TRADING_MODE", "paper"), operation=operation)

    def execute_intent(self, *, intent: OrderIntent) -> ExecutionResult:
        # Smart routing (optional): can downgrade before risk/broker.
        routing: SmartRoutingDecision | None = None
        if self.enable_smart_routing and self.router is not None:
            routing = self.router.analyze_intent(intent=intent)
            if not routing.should_execute:
                decision = RiskDecision(allowed=False, reason="smart_routing_downgraded", checks=[{"check": "smart_routing", **routing.__dict__}])
                return ExecutionResult(status="downgraded", risk=decision, routing=routing, message=routing.reason)

        # Optional: reserve notional budget (best-effort; always release).
        reservation = None
        try:
            if self._reservations is not None:
                meta = intent.metadata or {}
                tenant_id = str(meta.get("tenant_id") or os.getenv("EXEC_TENANT_ID") or "").strip() or "default"
                notional = float(meta.get("notional_usd") or 0.0)
                reservation = self._reservations.reserve(
                    tenant_id=tenant_id,
                    broker_account_id=intent.broker_account_id,
                    client_intent_id=str(intent.client_intent_id or intent.metadata.get("client_intent_id") or "unknown"),
                    amount_usd=notional,
                    meta={"symbol": intent.symbol, "strategy_id": intent.strategy_id},
                )
        except Exception:
            reservation = None

        try:
            # Agent execution budgets (fail-closed for missing required metadata).
            b = self._check_and_record_budgets(intent=intent)
            if b is not None and not b.allowed:
                if reservation is not None:
                    try:
                        reservation.release(outcome="rejected", error=b.reason)
                    except Exception:
                        pass
                return ExecutionResult(status="rejected", risk=b, routing=routing, message=b.reason)

            # Risk.
            decision = self.risk.validate(intent=intent)
            if not decision.allowed:
                if reservation is not None:
                    try:
                        reservation.release(outcome="rejected", error=decision.reason)
                    except Exception:
                        pass
                return ExecutionResult(status="rejected", risk=decision, routing=routing, message=decision.reason)

            # Dry-run never routes.
            if self.dry_run:
                self._record_budget_use(intent=intent)
                if reservation is not None:
                    try:
                        reservation.release(outcome="dry_run", error=None)
                    except Exception:
                        pass
                return ExecutionResult(status="dry_run", risk=decision, routing=routing, message="dry_run")

            # Non-dry-run: enforce authority boundaries.
            self._enforce_paper_only_if_possible(operation="execution_engine.execute_intent")
            require_live_mode(action="execute_intent")
            require_execution_enabled(operation="execution_engine.execute_intent", context={"strategy_id": intent.strategy_id, "symbol": intent.symbol})

            broker_order = self._broker.place_order(intent=intent)
            broker_order_id = str(broker_order.get("id") or "") or None
            self._record_budget_use(intent=intent)
            if reservation is not None:
                try:
                    reservation.release(outcome="submitted", error=None)
                except Exception:
                    pass
            return ExecutionResult(status="submitted", risk=decision, broker_order_id=broker_order_id, broker_order=broker_order, routing=routing)
        except Exception as e:
            if reservation is not None:
                try:
                    reservation.release(outcome="exception", error=f"{e.__class__.__name__}: {e}")
                except Exception:
                    pass
            raise

    def cancel(self, *, broker_order_id: str) -> Dict[str, Any]:
        require_execution_enabled(operation="execution_engine.cancel", context={"broker_order_id": broker_order_id})
        self._enforce_paper_only_if_possible(operation="execution_engine.cancel")
        return self._broker.cancel_order(broker_order_id=broker_order_id)

    def sync_and_ledger_if_filled(self, *, broker_order_id: str) -> Dict[str, Any]:
        require_execution_enabled(operation="execution_engine.sync_and_ledger_if_filled", context={"broker_order_id": broker_order_id})
        self._enforce_paper_only_if_possible(operation="execution_engine.sync_and_ledger_if_filled")
        order = self._broker.get_order_status(broker_order_id=broker_order_id)
        # Ledger writes are intentionally best-effort and only on fills.
        try:
            filled_qty = float(order.get("filled_qty") or 0.0)
        except Exception:
            filled_qty = 0.0
        if filled_qty > 0 and getattr(self.risk, "ledger", None) is not None and hasattr(self.risk.ledger, "write_fill"):
            try:
                # We don't have the original intent here; ledger implementations can accept partial info.
                self.risk.ledger.write_fill(intent=None, broker=self.broker_name, broker_order=order, fill=order)
            except Exception:
                pass
        return order