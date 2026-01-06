from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.common.replay_events import build_replay_event, dumps_replay_event, set_replay_context
from backend.execution.engine import (
    AlpacaBroker,
    DryRunBroker,
    ExecutionEngine,
    ExecutionResult,
    OrderIntent,
)
from backend.common.vertex_ai import init_vertex_ai_or_log

logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


class ExecuteIntentRequest(BaseModel):
    strategy_id: str = Field(..., description="Strategy identifier")
    broker_account_id: str = Field(..., description="Broker account id (e.g. paper/live account)")
    symbol: str = Field(..., description="Ticker symbol, e.g. SPY")
    side: str = Field(..., description="buy|sell")
    qty: float = Field(..., gt=0, description="Order quantity")

    order_type: str = Field(default="market", description="market|limit|...")
    time_in_force: str = Field(default="day", description="day|gtc|...")
    limit_price: Optional[float] = Field(default=None, description="Required for limit orders")

    client_intent_id: Optional[str] = Field(
        default=None, description="Optional idempotency/audit identifier"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecuteIntentResponse(BaseModel):
    status: str
    risk: dict[str, Any]
    broker_order_id: Optional[str] = None
    broker_order: Optional[dict[str, Any]] = None
    message: Optional[str] = None


def _engine_from_env() -> ExecutionEngine:
    """
    Constructs the engine from env vars.

    ADC / Firestore:
    - Uses `backend.persistence.firebase_client` which initializes Firebase Admin SDK via ADC.
    - On Cloud Run, attach a service account with Firestore permissions.
    """
    dry_run = _bool_env("EXEC_DRY_RUN", True)
    broker = DryRunBroker() if dry_run else AlpacaBroker()
    return ExecutionEngine(broker=broker, broker_name="alpaca", dry_run=dry_run)


app = FastAPI(title="AgentTrader Execution Engine")

@app.on_event("startup")
def _startup() -> None:
    # Emit a replay-safe startup marker for post-mortem timelines.
    try:
        set_replay_context(agent_name=os.getenv("AGENT_NAME") or "execution-engine")
        logger.info(
            "%s",
            dumps_replay_event(
                build_replay_event(
                    event="startup",
                    component="backend.services.execution_service.app",
                    data={
                        "service": "execution-engine",
                        "dry_run_default": _bool_env("EXEC_DRY_RUN", True),
                        "log_level": os.getenv("LOG_LEVEL", "INFO"),
                    },
                )
            ),
        )
    except Exception:
        pass
    # Best-effort: validate Vertex AI model config without crashing the service.
    try:
        init_vertex_ai_or_log()
    except Exception as e:  # pragma: no cover
        logger.warning("Vertex AI validation skipped (non-fatal): %s", e)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "execution-engine"}


@app.post("/execute", response_model=ExecuteIntentResponse)
def execute(req: ExecuteIntentRequest) -> ExecuteIntentResponse:
    engine = _engine_from_env()
    # Prefer caller-provided trace_id; fall back to client_intent_id.
    trace_id = str(req.metadata.get("trace_id") or req.client_intent_id or "").strip() or None
    if trace_id:
        set_replay_context(trace_id=trace_id)
    intent = OrderIntent(
        strategy_id=req.strategy_id,
        broker_account_id=req.broker_account_id,
        symbol=req.symbol,
        side=req.side,
        qty=req.qty,
        order_type=req.order_type,
        time_in_force=req.time_in_force,
        limit_price=req.limit_price,
        client_intent_id=req.client_intent_id or None,
        metadata=req.metadata,
    )

    try:
        result: ExecutionResult = engine.execute_intent(intent=intent)
    except Exception as e:
        logger.exception("exec_service.execute_failed: %s", e)
        try:
            logger.error(
                "%s",
                dumps_replay_event(
                    build_replay_event(
                        event="state_transition",
                        component="backend.services.execution_service.app",
                        data={
                            "from_state": "intent_received",
                            "to_state": "execute_failed",
                            "strategy_id": req.strategy_id,
                            "symbol": req.symbol,
                            "client_intent_id": req.client_intent_id,
                            "error": str(e),
                        },
                        trace_id=trace_id,
                        agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                    )
                ),
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="execution_failed") from e

    # Always log an audit event (safe JSON; broker_order may contain ids, not secrets).
    try:
        logger.info(
            "exec_service.execute_result %s",
            json.dumps(
                {
                    "status": result.status,
                    "risk": {
                        "allowed": result.risk.allowed,
                        "reason": result.risk.reason,
                        "checks": result.risk.checks,
                    },
                    "broker_order_id": result.broker_order_id,
                }
            ),
        )
    except Exception:
        pass

    resp = ExecuteIntentResponse(
        status=result.status,
        risk={
            "allowed": result.risk.allowed,
            "reason": result.risk.reason,
            "checks": result.risk.checks,
        },
        broker_order_id=result.broker_order_id,
        broker_order=result.broker_order,
        message=result.message,
    )

    # Reject intents via HTTP 409 for easy callers.
    if result.status == "rejected":
        raise HTTPException(status_code=409, detail=resp.model_dump())

    return resp


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


_configure_logging()

