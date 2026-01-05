from fastapi import APIRouter, Request
from uuid import UUID
from decimal import Decimal

from ..db import get_db
from ..models import TradeCheckRequest, RiskCheckResult
from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext
from backend.tenancy.paths import tenant_collection

router = APIRouter(prefix="/risk", tags=["risk"])

COLLECTION_RISK_LIMITS = "risk_limits"


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

    if payload.strategy_id:
        result = apply_limits(strat_limits, "strategy")
        if result is not None:
            return result

    result = apply_limits(acct_limits, "account")
    if result is not None:
        return result

    return RiskCheckResult(allowed=True, reason=None, scope=None)
