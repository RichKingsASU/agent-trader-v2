
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import os

from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext

from ..db import build_raw_order, insert_paper_order
from ..models import PaperOrderCreate
from backend.common.a2a_sdk import RiskAgentClient
from backend.contracts.risk import TradeCheckRequest

router = APIRouter()

RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://127.0.0.1:8002")


class PaperOrderRequest(BaseModel):
    broker_account_id: UUID
    strategy_id: UUID
    symbol: str
    instrument_type: str
    side: str
    order_type: str
    time_in_force: str = "day"
    notional: float
    quantity: float | None = None


@router.post("/paper_orders", tags=["paper_orders"])
async def create_paper_order(order: PaperOrderRequest, request: Request):
    ctx: TenantContext = get_tenant_context(request)
    # 1. Run risk check
    try:
        risk_req = TradeCheckRequest(
            broker_account_id=order.broker_account_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            notional=str(order.notional),
            side=order.side,
            current_open_positions=0,
            current_trades_today=0,
            current_day_loss="0.0",
            current_day_drawdown="0.0",
        )
        client = RiskAgentClient(RISK_SERVICE_URL)
        risk_result = await client.check_trade(
            risk_req,
            authorization=request.headers.get("Authorization", ""),
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Error connecting to risk service: {e}") from e
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code, detail=f"Risk service error: {e.response.text}"
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk service request failed: {e}") from e

    # 2. If allowed, insert paper order
    if risk_result.allowed:
        logical_order = {
            "uid": ctx.uid,
            "broker_account_id": str(order.broker_account_id),
            "strategy_id": str(order.strategy_id),
            "symbol": order.symbol,
            "instrument_type": order.instrument_type,
            "side": order.side,
            "order_type": order.order_type,
            "time_in_force": order.time_in_force,
            "notional": order.notional,
            "quantity": order.quantity,
        }

        payload = PaperOrderCreate(
            uid=ctx.uid,
            broker_account_id=order.broker_account_id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            instrument_type=order.instrument_type,
            side=order.side,
            order_type=order.order_type,
            time_in_force=order.time_in_force,
            notional=order.notional,
            quantity=order.quantity,
            risk_allowed=True,
            risk_scope=risk_result.scope,
            risk_reason=risk_result.reason,
            raw_order=build_raw_order(logical_order),
            status="simulated",
        )
        return insert_paper_order(tenant_id=ctx.tenant_id, payload=payload)
    else:
        # If risk check fails, return the reason
        raise HTTPException(status_code=400, detail=risk_result.model_dump(mode="json"))

