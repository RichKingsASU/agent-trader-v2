from fastapi import APIRouter, HTTPException, Request
from typing import List
from uuid import UUID, uuid4
import os
from google.cloud import firestore
from pydantic import BaseModel
import httpx

from backend.persistence.firestore_retry import with_firestore_retry
from ..db import get_db, insert_paper_order
from ..models import StrategyCreate, Strategy, PaperOrderCreate, PaperOrder
from backend.tenancy.auth import get_tenant_context
from backend.tenancy.context import TenantContext
from backend.tenancy.paths import tenant_collection
from backend.common.a2a_sdk import RiskAgentSyncClient
from backend.contracts.risk import TradeCheckRequest

router = APIRouter(prefix="/strategies", tags=["strategies"])

COLLECTION_STRATEGIES = "strategies"
RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://127.0.0.1:8002")

class PaperOrderSimulateRequest(BaseModel):
    correlation_id: str | None = None
    signal_id: str | None = None
    allocation_id: str | None = None
    execution_id: str | None = None
    broker_account_id: UUID
    strategy_id: UUID
    symbol: str
    instrument_type: str
    side: str
    order_type: str
    time_in_force: str = "day"
    notional: float
    quantity: float | None = None



def _doc_to_strategy(d: dict) -> Strategy:
    return Strategy(
        id=UUID(str(d["id"])),
        uid=str(d["uid"]),
        name=d["name"],
        description=d.get("description"),
        status=d.get("status", "draft"),
        target_symbols=list(d.get("target_symbols") or []),
        instrument=d.get("instrument", "option"),
        broker_account_id=UUID(str(d["broker_account_id"])),
        config=d.get("config") or {},
        trading_session=d.get("trading_session") or {},
    )


@router.get("/", response_model=List[Strategy])
def list_strategies(request: Request):
    ctx: TenantContext = get_tenant_context(request)
    db = get_db()
    rows: list[Strategy] = []
    q = tenant_collection(db, tenant_id=ctx.tenant_id, collection_name=COLLECTION_STRATEGIES).where(
        "uid", "==", ctx.uid
    )
    for doc in q.stream():
        d = doc.to_dict() or {}
        d["id"] = d.get("id") or doc.id
        rows.append(_doc_to_strategy(d))
    return rows


@router.post("/", response_model=Strategy)
def create_strategy(payload: StrategyCreate, request: Request):
    ctx: TenantContext = get_tenant_context(request)
    db = get_db()
    strategy_id = uuid4()
    doc = {
        "id": str(strategy_id),
        "uid": ctx.uid,
        "name": payload.name,
        "description": payload.description,
        "status": payload.status,
        "target_symbols": payload.target_symbols,
        "instrument": payload.instrument,
        "broker_account_id": str(payload.broker_account_id),
        "config": payload.config,
        "trading_session": payload.trading_session,
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    with_firestore_retry(
        lambda: tenant_collection(db, tenant_id=ctx.tenant_id, collection_name=COLLECTION_STRATEGIES)
        .document(str(strategy_id))
        .set(doc, merge=False)
    )
    return _doc_to_strategy(doc)


@router.post("/simulate-order", response_model=PaperOrder)
def simulate_order(payload: PaperOrderSimulateRequest, request: Request):
    ctx: TenantContext = get_tenant_context(request)
    corr = risk_correlation_id(correlation_id=payload.correlation_id, headers=dict(request.headers))
    payload.correlation_id = corr
    if payload.execution_id is None:
        payload.execution_id = str(uuid4())
    # For now, we'll assume a simple risk check that always passes.
    # In the future, we can add a more sophisticated risk check here.
    
    try:
        risk_req = TradeCheckRequest(
            broker_account_id=payload.broker_account_id,
            strategy_id=payload.strategy_id,
            symbol=payload.symbol,
            notional=str(payload.notional),
            side=payload.side,
            current_open_positions=0,
            current_trades_today=0,
            current_day_loss="0.0",
            current_day_drawdown="0.0",
        )
        risk_client = RiskAgentSyncClient(RISK_SERVICE_URL)
        risk_result = risk_client.check_trade(
            risk_req,
            authorization=request.headers.get("Authorization", ""),
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to risk service: {e}") from e


    if not risk_result.allowed:
        raise HTTPException(status_code=400, detail=f"Risk check failed: {risk_result.reason}")

    paper_order = insert_paper_order(
        tenant_id=ctx.tenant_id,
        payload=PaperOrderCreate(
            correlation_id=corr,
            signal_id=payload.signal_id,
            allocation_id=payload.allocation_id,
            execution_id=payload.execution_id,
            uid=ctx.uid,
            broker_account_id=payload.broker_account_id,
            strategy_id=payload.strategy_id,
            symbol=payload.symbol,
            instrument_type=payload.instrument_type,
            side=payload.side,
            order_type=payload.order_type,
            time_in_force=payload.time_in_force,
            notional=payload.notional,
            quantity=payload.quantity,
            risk_allowed=True,
            risk_scope=risk_result.scope,
            risk_reason=risk_result.reason,
            raw_order={
                "correlation_id": corr,
                "signal_id": payload.signal_id,
                "allocation_id": payload.allocation_id,
                "execution_id": payload.execution_id,
                "instrument_type": payload.instrument_type,
                "symbol": payload.symbol,
                "side": payload.side,
                "order_type": payload.order_type,
                "time_in_force": payload.time_in_force,
                "notional": payload.notional,
                "quantity": payload.quantity,
                "strategy_id": str(payload.strategy_id),
                "broker_account_id": str(payload.broker_account_id),
                "uid": ctx.uid,
            },
            status="simulated",
        ),
    )
    if not paper_order:
        raise HTTPException(status_code=500, detail="Failed to create paper order")

    return paper_order
