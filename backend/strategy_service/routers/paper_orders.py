
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext

from ..db import build_raw_order, insert_paper_order
from ..models import PaperOrderCreate

router = APIRouter()


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
    async with httpx.AsyncClient() as client:
        try:
            risk_check_payload = {
                "broker_account_id": str(order.broker_account_id),
                "strategy_id": str(order.strategy_id),
                "symbol": order.symbol,
                "notional": str(order.notional),
                "side": order.side,
                "current_open_positions": 0,
                "current_trades_today": 0,
                "current_day_loss": "0.0",
                "current_day_drawdown": "0.0",
            }
            response = await client.post(
                "http://127.0.0.1:8002/risk/check-trade",
                json=risk_check_payload,
                headers={"Authorization": request.headers.get("Authorization", "")},
            )
            response.raise_for_status()
            risk_result = response.json()
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=500, detail=f"Error connecting to risk service: {e}"
            )
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code, detail=f"Risk service error: {e.response.text}"
            )

    # 2. If allowed, insert paper order
    if risk_result.get("allowed"):
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
            risk_scope=risk_result.get("scope"),
            risk_reason=risk_result.get("reason"),
            raw_order=build_raw_order(logical_order),
            status="simulated",
        )
        return insert_paper_order(tenant_id=ctx.tenant_id, payload=payload)
    else:
        # If risk check fails, return the reason
        raise HTTPException(status_code=400, detail=risk_result)

