from fastapi import APIRouter, Request
from uuid import UUID
from decimal import Decimal
import logging
import time

from ..db import get_db
from ..models import TradeCheckRequest, RiskCheckResult
from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext
from backend.tenancy.paths import tenant_collection
from backend.common.logging import log_event
from backend.observability.risk_signals import risk_correlation_id

router = APIRouter(prefix="/risk", tags=["risk"])
logger = logging.getLogger(__name__)

COLLECTION_RISK_LIMITS = "risk_limits"

_LAST_DD: dict[str, tuple[float, float]] = {}


def _drawdown_pct(x: Decimal) -> float:
    """
    Best-effort normalize drawdown to percent.
    Accept either:
    - fraction (0.02) -> 2.0%
    - percent (2.0) -> 2.0%
    """
    try:
        v = float(x)
    except Exception:
        return 0.0
    if 0.0 <= v <= 1.0:
        return v * 100.0
    return v


def _drawdown_velocity_ppm(*, key: str, drawdown_pct: float) -> float | None:
    now_s = time.time()
    prev = _LAST_DD.get(key)
    _LAST_DD[key] = (now_s, drawdown_pct)
    if not prev:
        return None
    prev_s, prev_dd = prev
    dt_min = max(0.0, (now_s - prev_s) / 60.0)
    if dt_min <= 0.0:
        return None
    return (drawdown_pct - prev_dd) / dt_min


def _risk_limits_query(
    *,
    tenant_id: str,
    uid: str,
    broker_account_id: UUID,
    scope: str,
    strategy_id: UUID | None,
):
    db = get_db()
    q = (
        tenant_collection(db, tenant_id=tenant_id, collection_name=COLLECTION_RISK_LIMITS)
        .where("uid", "==", uid)
        .where("broker_account_id", "==", str(broker_account_id))
        .where("scope", "==", scope)
    )
    if scope == "strategy":
        q = q.where("strategy_id", "==", str(strategy_id))
    return q


def _first_limit_dict(q) -> dict | None:
    docs = list(q.limit(1).stream())
    if not docs:
        return None
    d = docs[0].to_dict() or {}
    d["id"] = docs[0].id
    return d


@router.get("/limits")
def get_risk_limits(request: Request, broker_account_id: UUID, strategy_id: UUID | None = None):
    ctx: TenantContext = get_tenant_context(request)
    scope = "strategy" if strategy_id else "account"
    q = _risk_limits_query(
        tenant_id=ctx.tenant_id,
        uid=ctx.uid,
        broker_account_id=broker_account_id,
        scope=scope,
        strategy_id=strategy_id,
    )
    rows: list[dict] = []
    for doc in q.stream():
        d = doc.to_dict() or {}
        d["id"] = doc.id
        rows.append(d)
    return rows


@router.post("/check-trade", response_model=RiskCheckResult)
def check_trade(payload: TradeCheckRequest, request: Request):
    ctx: TenantContext = get_tenant_context(request)
    corr = risk_correlation_id(correlation_id=payload.correlation_id, headers=dict(request.headers))
    strat_limits = None
    if payload.strategy_id:
        strat_limits = _first_limit_dict(
            _risk_limits_query(
                tenant_id=ctx.tenant_id,
                uid=ctx.uid,
                broker_account_id=payload.broker_account_id,
                scope="strategy",
                strategy_id=payload.strategy_id,
            ).where("enabled", "==", True)
        )

    acct_limits = _first_limit_dict(
        _risk_limits_query(
            tenant_id=ctx.tenant_id,
            uid=ctx.uid,
            broker_account_id=payload.broker_account_id,
            scope="account",
            strategy_id=None,
        ).where("enabled", "==", True)
    )

    def apply_limits(limits: dict, scope: str) -> RiskCheckResult | None:
        if not limits:
            return None

        max_notional_per_trade = limits.get("max_notional_per_trade")
        if max_notional_per_trade is not None and payload.notional > Decimal(str(max_notional_per_trade)):
            return RiskCheckResult(
                allowed=False,
                reason=f"Notional {payload.notional} exceeds max_notional_per_trade {max_notional_per_trade}",
                scope=scope,
            )

        max_trades_per_day = limits.get("max_trades_per_day")
        if max_trades_per_day is not None and payload.current_trades_today + 1 > max_trades_per_day:
            return RiskCheckResult(
                allowed=False,
                reason=f"Trade count {payload.current_trades_today + 1} exceeds max_trades_per_day {max_trades_per_day}",
                scope=scope,
            )

        max_open_positions = limits.get("max_open_positions")
        if max_open_positions is not None and payload.current_open_positions + 1 > max_open_positions:
            return RiskCheckResult(
                allowed=False,
                reason=f"Open positions {payload.current_open_positions + 1} exceeds max_open_positions {max_open_positions}",
                scope=scope,
            )

        max_loss_per_day = limits.get("max_loss_per_day")
        if (
            max_loss_per_day is not None
            and payload.current_day_loss < Decimal(0)
            and abs(payload.current_day_loss) >= Decimal(str(max_loss_per_day))
        ):
            return RiskCheckResult(
                allowed=False,
                reason=f"Current day loss {payload.current_day_loss} exceeds max_loss_per_day {max_loss_per_day}",
                scope=scope,
            )

        max_drawdown_per_day = limits.get("max_drawdown_per_day")
        if max_drawdown_per_day is not None and payload.current_day_drawdown > Decimal(str(max_drawdown_per_day)):
            return RiskCheckResult(
                allowed=False,
                reason=f"Current day drawdown {payload.current_day_drawdown} exceeds max_drawdown_per_day {max_drawdown_per_day}",
                scope=scope,
            )

        return None

    # Emit pre-decision risk signals (emit-only; no UI/dashboards)
    try:
        dd_pct = _drawdown_pct(payload.current_day_drawdown)
        dd_vel = _drawdown_velocity_ppm(
            key=f"{ctx.tenant_id}:{ctx.uid}:{payload.broker_account_id}:{payload.strategy_id or '-'}",
            drawdown_pct=dd_pct,
        )

        active_limits = strat_limits if payload.strategy_id and strat_limits else acct_limits
        max_notional = None
        util_vs_max_notional_pct = None
        if isinstance(active_limits, dict) and active_limits.get("max_notional_per_trade") is not None:
            try:
                max_notional = float(active_limits["max_notional_per_trade"])
                util_vs_max_notional_pct = (float(payload.notional) / max_notional) * 100.0 if max_notional > 0 else None
            except Exception:
                pass

        log_event(
            logger,
            "risk.trade_check",
            severity="INFO",
            correlation_id=corr,
            tenant_id=ctx.tenant_id,
            uid=ctx.uid,
            broker_account_id=str(payload.broker_account_id),
            strategy_id=str(payload.strategy_id) if payload.strategy_id else None,
            symbol=payload.symbol,
            side=payload.side,
            requested_notional=float(payload.notional),
            # Required risk signals (best-effort in this service)
            capital_utilization_pct=None,
            risk_per_strategy_usd=float(payload.notional),
            risk_per_strategy_pct_equity=None,
            drawdown_pct=dd_pct,
            drawdown_velocity_pct_per_min=dd_vel,
            # Correlation chain ids
            signal_id=payload.signal_id,
            allocation_id=payload.allocation_id,
            execution_id=payload.execution_id,
            # Limit context (for "risk per strategy" interpretation)
            limits_scope="strategy" if payload.strategy_id else "account",
            limits_id=(active_limits or {}).get("id") if isinstance(active_limits, dict) else None,
            max_notional_per_trade=max_notional,
            utilization_vs_max_notional_pct=util_vs_max_notional_pct,
        )
    except Exception:
        pass

    if payload.strategy_id:
        result = apply_limits(strat_limits, "strategy")
        if result is not None:
            try:
                log_event(
                    logger,
                    "risk.trade_check.denied",
                    severity="WARNING",
                    correlation_id=corr,
                    tenant_id=ctx.tenant_id,
                    uid=ctx.uid,
                    scope=result.scope,
                    reason=result.reason,
                    signal_id=payload.signal_id,
                    allocation_id=payload.allocation_id,
                    execution_id=payload.execution_id,
                )
            except Exception:
                pass
            return result

    result = apply_limits(acct_limits, "account")
    if result is not None:
        try:
            log_event(
                logger,
                "risk.trade_check.denied",
                severity="WARNING",
                correlation_id=corr,
                tenant_id=ctx.tenant_id,
                uid=ctx.uid,
                scope=result.scope,
                reason=result.reason,
                signal_id=payload.signal_id,
                allocation_id=payload.allocation_id,
                execution_id=payload.execution_id,
            )
        except Exception:
            pass
        return result

    try:
        log_event(
            logger,
            "risk.trade_check.allowed",
            severity="INFO",
            correlation_id=corr,
            tenant_id=ctx.tenant_id,
            uid=ctx.uid,
            signal_id=payload.signal_id,
            allocation_id=payload.allocation_id,
            execution_id=payload.execution_id,
        )
    except Exception:
        pass
    return RiskCheckResult(allowed=True, reason=None, scope=None)
