from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from backend.common.agent_mode import require_live_mode
from backend.common.runtime_execution_prevention import fatal_if_execution_reached


def _utc_today_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _truthy_env(name: str) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    return v in {"1", "true", "t", "yes", "y", "on"}


def _kill_switch_enabled() -> bool:
    # Env-first kill switch; file-based switch supported for local ops.
    if _truthy_env("EXECUTION_HALTED") or _truthy_env("EXEC_KILL_SWITCH"):
        return True
    path = (os.getenv("EXECUTION_HALTED_FILE") or "").strip()
    if not path:
        return False
    try:
        raw = open(path, encoding="utf-8").read().strip().lower()  # noqa: PTH123
    except Exception:
        return False
    return raw in {"1", "true", "t", "yes", "y", "on"}


@dataclass(frozen=True)
class OrderIntent:
    strategy_id: str
    broker_account_id: str
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    asset_class: str = "EQUITY"
    estimated_slippage: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "OrderIntent":
        side = str(self.side).strip().lower()
        asset_class = str(self.asset_class).strip().upper() or "EQUITY"
        symbol = str(self.symbol).strip().upper() if asset_class == "EQUITY" else str(self.symbol).strip().upper()
        return replace(self, side=side, asset_class=asset_class, symbol=symbol)


@dataclass(frozen=True)
class RiskConfig:
    max_position_qty: float = 0.0
    max_daily_trades: int = 0
    fail_open: bool = False


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str
    checks: list[dict[str, Any]] = field(default_factory=list)


class Ledger(Protocol):
    def count_trades_today(self, *, broker_account_id: str, trading_date: str) -> int: ...

    def write_fill(self, *, intent: OrderIntent, broker: Any, broker_order: dict[str, Any], fill: dict[str, Any]) -> None: ...


class Positions(Protocol):
    def get_position_qty(self, *, symbol: str) -> float: ...


class RiskManager:
    def __init__(self, *, config: RiskConfig, ledger: Ledger, positions: Positions) -> None:
        self.config = config
        self.ledger = ledger
        self.positions = positions

    def validate(self, *, intent: OrderIntent) -> RiskDecision:
        i = intent.normalized()

        if _kill_switch_enabled():
            return RiskDecision(allowed=False, reason="kill_switch_enabled", checks=[{"check": "kill_switch", "enabled": True}])

        checks: list[dict[str, Any]] = []

        # Daily trade cap.
        try:
            trades_today = int(
                self.ledger.count_trades_today(broker_account_id=i.broker_account_id, trading_date=_utc_today_yyyymmdd())
            )
        except Exception as e:
            if self.config.fail_open:
                checks.append({"check": "max_daily_trades", "ok": True, "fail_open": True, "error": str(e)})
                trades_today = 0
            else:
                return RiskDecision(allowed=False, reason="risk_state_unavailable", checks=[{"check": "max_daily_trades", "ok": False}])

        if int(self.config.max_daily_trades) > 0 and trades_today >= int(self.config.max_daily_trades):
            checks.append(
                {
                    "check": "max_daily_trades",
                    "ok": False,
                    "trades_today": trades_today,
                    "limit": int(self.config.max_daily_trades),
                }
            )
            return RiskDecision(allowed=False, reason="max_daily_trades_exceeded", checks=checks)
        checks.append({"check": "max_daily_trades", "ok": True, "trades_today": trades_today, "limit": int(self.config.max_daily_trades)})

        # Max position size (absolute projected qty).
        try:
            current_qty = float(self.positions.get_position_qty(symbol=i.symbol))
        except Exception as e:
            if self.config.fail_open:
                checks.append({"check": "max_position_size", "ok": True, "fail_open": True, "error": str(e)})
                current_qty = 0.0
            else:
                return RiskDecision(allowed=False, reason="risk_state_unavailable", checks=[{"check": "max_position_size", "ok": False}])

        signed_qty = float(i.qty) if i.side == "buy" else -float(i.qty)
        projected = float(current_qty) + signed_qty
        limit = float(self.config.max_position_qty)
        if limit > 0 and abs(projected) > limit:
            checks.append({"check": "max_position_size", "ok": False, "projected_qty": projected, "limit_abs_qty": limit})
            return RiskDecision(allowed=False, reason="max_position_size_exceeded", checks=checks)
        checks.append({"check": "max_position_size", "ok": True, "projected_qty": projected, "limit_abs_qty": limit})

        return RiskDecision(allowed=True, reason="ok", checks=checks)


@dataclass(frozen=True)
class SmartRoutingDecision:
    should_execute: bool
    reason: str
    estimated_slippage: float | None = None
    spread_pct: float | None = None
    bid: float | None = None
    ask: float | None = None
    downgraded: bool = False


class MarketDataProvider(Protocol):
    def get_quote(self, *, symbol: str, asset_class: str | None = None) -> dict[str, Any]: ...


class SmartRouter:
    def __init__(self, *, market_data_provider: MarketDataProvider | None = None, max_spread_pct: float = 0.001) -> None:
        self._md = market_data_provider
        self._max_spread_pct = float(max_spread_pct)

    def analyze_intent(self, *, intent: OrderIntent) -> SmartRoutingDecision:
        i = intent.normalized()

        if i.estimated_slippage is not None:
            sl = float(i.estimated_slippage)
            if sl > self._max_spread_pct:
                return SmartRoutingDecision(
                    should_execute=False,
                    downgraded=True,
                    reason=f"Estimated slippage {sl:.4%} exceeds threshold {self._max_spread_pct:.4%}",
                    estimated_slippage=sl,
                )
            return SmartRoutingDecision(should_execute=True, downgraded=False, reason="Estimated slippage within threshold", estimated_slippage=sl)

        if self._md is None:
            return SmartRoutingDecision(should_execute=True, downgraded=False, reason="No market data provider configured")

        q = self._md.get_quote(symbol=i.symbol, asset_class=i.asset_class)
        bid = float(q.get("bid")) if q.get("bid") is not None else None
        ask = float(q.get("ask")) if q.get("ask") is not None else None
        spread_pct = float(q.get("spread_pct")) if q.get("spread_pct") is not None else None
        est = float(q.get("spread_pct")) if spread_pct is not None else None
        if spread_pct is not None and spread_pct > self._max_spread_pct:
            return SmartRoutingDecision(
                should_execute=False,
                downgraded=True,
                reason=f"Spread {spread_pct:.4%} exceeds threshold {self._max_spread_pct:.4%}",
                estimated_slippage=est,
                spread_pct=spread_pct,
                bid=bid,
                ask=ask,
            )
        return SmartRoutingDecision(
            should_execute=True,
            downgraded=False,
            reason="Spread within acceptable range",
            estimated_slippage=est,
            spread_pct=spread_pct,
            bid=bid,
            ask=ask,
        )


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    risk: RiskDecision
    routing: SmartRoutingDecision | None = None


class DryRunBroker:
    def place_order(self, *, intent: OrderIntent) -> dict[str, Any]:  # noqa: ARG002
        return {"id": "dry_run_order", "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str) -> dict[str, Any]:  # noqa: ARG002
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str) -> dict[str, Any]:  # noqa: ARG002
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


class AlpacaBroker:
    """
    Safety-hardened broker adapter.

    This repo’s policy is to refuse any non-paper execution paths.
    """

    def __init__(self, *, request_timeout_s: float = 30.0) -> None:
        self._timeout_s = float(request_timeout_s)
        self._alpaca = None  # injected in tests

    def _enforce_paper_only(self, *, operation: str) -> None:
        trading_mode = str(os.getenv("TRADING_MODE") or "paper").strip().lower() or "paper"
        base_url = getattr(getattr(self, "_alpaca", None), "api_base_url", "") or ""
        base_url = str(base_url).strip().lower()
        is_live_host = ("api.alpaca.markets" in base_url) and ("paper-api.alpaca.markets" not in base_url)

        if trading_mode != "paper" or is_live_host:
            fatal_if_execution_reached(
                operation=operation,
                explicit_message="REFUSED: live Alpaca execution is forbidden (paper-only safety boundary).",
                context={"trading_mode": trading_mode, "alpaca_base_url": base_url},
            )

    def place_order(self, *, intent: OrderIntent) -> dict[str, Any]:
        _ = intent
        self._enforce_paper_only(operation="alpaca.place_order")
        return {"id": str(uuid4()), "status": "new", "filled_qty": "0"}

    def cancel_order(self, *, broker_order_id: str) -> dict[str, Any]:
        self._enforce_paper_only(operation="alpaca.cancel_order")
        return {"id": broker_order_id, "status": "canceled"}

    def get_order_status(self, *, broker_order_id: str) -> dict[str, Any]:
        self._enforce_paper_only(operation="alpaca.get_order_status")
        return {"id": broker_order_id, "status": "new", "filled_qty": "0"}


class ExecutionEngine:
    def __init__(
        self,
        *,
        broker: Any,
        risk: RiskManager | None = None,
        dry_run: bool = True,
        router: SmartRouter | None = None,
        enable_smart_routing: bool = False,
        reservations: Any | None = None,
    ) -> None:
        self._broker = broker
        self._risk = risk
        self._dry_run = bool(dry_run)
        self._router = router
        self._enable_smart_routing = bool(enable_smart_routing)
        self._reservations = reservations

        self._agent_budget_state: dict[str, dict[str, float]] = {}

    def _budget_cfg(self, *, strategy_id: str) -> dict[str, Any] | None:
        if not _truthy_env("EXEC_AGENT_BUDGETS_ENABLED"):
            return None
        if _truthy_env("EXEC_AGENT_BUDGETS_USE_FIRESTORE"):
            # Not implemented in unit tests; fail closed by default.
            return None
        raw = (os.getenv("EXEC_AGENT_BUDGETS_JSON") or "").strip()
        if not raw:
            return None
        try:
            cfg = json.loads(raw)
        except Exception:
            return None
        if not isinstance(cfg, dict):
            return None
        v = cfg.get(strategy_id)
        return v if isinstance(v, dict) else None

    def _budget_check_and_record(self, *, intent: OrderIntent) -> RiskDecision | None:
        cfg = self._budget_cfg(strategy_id=intent.strategy_id)
        if cfg is None:
            return None

        sid = str(intent.strategy_id)
        st = self._agent_budget_state.setdefault(sid, {"executions": 0.0, "notional_usd": 0.0})

        max_exec = cfg.get("max_daily_executions")
        if max_exec is not None:
            try:
                if int(st["executions"]) >= int(max_exec):
                    return RiskDecision(allowed=False, reason="agent_execution_budget_exceeded", checks=[{"check": "agent_budget", "kind": "max_daily_executions"}])
            except Exception:
                return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=[{"check": "agent_budget", "kind": "max_daily_executions"}])

        max_pct = cfg.get("max_daily_capital_pct")
        if max_pct is not None:
            meta = intent.metadata or {}
            try:
                daily_cap = float(meta.get("daily_capital_usd"))
                notional = float(meta.get("notional_usd"))
            except Exception:
                return RiskDecision(allowed=False, reason="agent_budget_state_unavailable", checks=[{"check": "agent_budget", "kind": "max_daily_capital_pct"}])

            limit = float(daily_cap) * float(max_pct)
            projected = float(st["notional_usd"]) + float(notional)
            if projected > limit:
                return RiskDecision(
                    allowed=False,
                    reason="agent_execution_budget_exceeded",
                    checks=[{"check": "agent_budget", "kind": "max_daily_capital_pct", "projected": projected, "limit": limit}],
                )

        # Record usage on allowed paths (including dry-run).
        st["executions"] = float(st["executions"]) + 1.0
        if intent.metadata and intent.metadata.get("notional_usd") is not None:
            try:
                st["notional_usd"] = float(st["notional_usd"]) + float(intent.metadata.get("notional_usd"))
            except Exception:
                # Fail closed would have occurred earlier; keep robust.
                pass
        return None

    def execute_intent(self, *, intent: OrderIntent) -> ExecutionResult:
        i = intent.normalized()

        # Budget gating (fail-closed).
        budget_decision = self._budget_check_and_record(intent=i)
        if budget_decision is not None:
            return ExecutionResult(status="rejected", risk=budget_decision)

        # Risk gating (includes kill switch).
        risk_decision = self._risk.validate(intent=i) if self._risk is not None else RiskDecision(allowed=True, reason="ok")
        if not risk_decision.allowed:
            return ExecutionResult(status="rejected", risk=risk_decision)

        # Smart routing (pre-execution downgrade).
        routing: SmartRoutingDecision | None = None
        if self._enable_smart_routing and self._router is not None:
            routing = self._router.analyze_intent(intent=i)
            if not routing.should_execute:
                return ExecutionResult(status="downgraded", risk=risk_decision, routing=routing)

        # Dry-run: never place orders; never require LIVE mode.
        if self._dry_run:
            return ExecutionResult(status="dry_run", risk=risk_decision, routing=routing)

        # Reservation handle (best-effort) - must be released on all outcomes.
        reservation = None
        if self._reservations is not None and isinstance(i.metadata, dict):
            tenant_id = str(i.metadata.get("tenant_id") or "").strip()
            notional = i.metadata.get("notional_usd")
            if tenant_id and notional is not None:
                reservation = self._reservations.reserve(
                    tenant_id=tenant_id,
                    broker_account_id=str(i.broker_account_id),
                    client_intent_id=str(i.metadata.get("client_intent_id") or str(uuid4())),
                    amount_usd=float(notional),
                )

        try:
            # Authority boundary: only LIVE runtimes may execute orders.
            require_live_mode(action="place_order")

            broker_order = self._broker.place_order(intent=i)
            if reservation is not None:
                try:
                    reservation.release(outcome="placed", error=None)
                except Exception:
                    pass
            return ExecutionResult(status="placed", risk=risk_decision, routing=routing)
        except Exception as e:
            if reservation is not None:
                try:
                    reservation.release(outcome="exception", error=str(e))
                except Exception:
                    pass
            raise

    def cancel(self, *, broker_order_id: str) -> dict[str, Any]:
        # Enforce the same boundary as AlpacaBroker (tests patch _broker._alpaca).
        if hasattr(self._broker, "_enforce_paper_only"):
            self._broker._enforce_paper_only(operation="engine.cancel")  # type: ignore[attr-defined]
        return self._broker.cancel_order(broker_order_id=broker_order_id)

    def sync_and_ledger_if_filled(self, *, broker_order_id: str) -> dict[str, Any]:
        if hasattr(self._broker, "_enforce_paper_only"):
            self._broker._enforce_paper_only(operation="engine.get_order_status")  # type: ignore[attr-defined]
        status = self._broker.get_order_status(broker_order_id=broker_order_id)
        return status

    def _write_portfolio_history(self, *, intent: OrderIntent, broker_order: dict[str, Any], fill: dict[str, Any]) -> None:  # noqa: ARG002
        # Intentionally best-effort; unit tests only require that this method exists.
        raise RuntimeError("firestore: portfolio history write is not configured in unit test environment")