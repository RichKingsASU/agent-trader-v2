from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.app_heartbeat_writer import install_app_heartbeat
from backend.common.logging import init_structured_logging, install_fastapi_request_id_middleware
from backend.contracts.v2.explainability import StrategyExplanation
from backend.observability.ops_json_logger import OpsLogger
from backend.observer.scalper_observer import ScalperObserver

logger = logging.getLogger(__name__)

init_structured_logging(service="scalper-observer")

app = FastAPI(title="Scalper Observer", description="Read-only trade explanation service (no execution side effects).")
install_fastapi_request_id_middleware(app, service="scalper-observer")
install_app_heartbeat(app, service_name="scalper-observer")


def _service_name() -> str:
    return str(os.getenv("SERVICE_NAME") or "scalper-observer")


@app.on_event("startup")
async def startup_event() -> None:
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="scalper-observer",
        intent="Serve read-only trade explanations derived from Firestore artifacts and structured logs.",
    )
    app.state.ops_logger = OpsLogger(_service_name())
    app.state.ready = True
    try:
        app.state.ops_logger.readiness(ready=True)  # type: ignore[attr-defined]
    except Exception:
        pass


@app.on_event("shutdown")
async def shutdown_event() -> None:
    try:
        app.state.ready = False
    except Exception:
        pass
    try:
        app.state.ops_logger.shutdown(phase="initiated")  # type: ignore[attr-defined]
    except Exception:
        pass


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Process is alive (do not gate on external dependencies).
    return {"status": "ok", "service": _service_name()}


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    ready = bool(getattr(app.state, "ready", False))
    return {"status": "ok" if ready else "not_ready", "service": _service_name()}


class ExplainRequest(BaseModel):
    signal_id: Optional[str] = Field(default=None, description="Signal document id (preferred if known).")
    correlation_id: Optional[str] = Field(default=None, description="Correlation id linking signal→execution→shadow artifacts.")
    start_time: Optional[str] = Field(default=None, description="Optional ISO time bound for log correlation.")
    end_time: Optional[str] = Field(default=None, description="Optional ISO time bound for log correlation.")
    write_explanation: bool = Field(
        default=False,
        description="If true, persist the explanation record (requires ALLOW_EXPLANATION_WRITES=true).",
    )
    explanation_collection: Optional[str] = Field(
        default=None,
        description="Firestore collection to store explanation records (only used when write_explanation=true).",
    )


@app.post("/explain", response_model=StrategyExplanation)
async def explain(req: ExplainRequest) -> StrategyExplanation:
    # Hard rule: observer must never influence execution. No broker calls, no control-plane writes.
    if not (req.signal_id or req.correlation_id):
        raise HTTPException(status_code=400, detail="Provide signal_id or correlation_id")
    obs = ScalperObserver()
    try:
        return obs.explain_record(
            signal_id=req.signal_id,
            correlation_id=req.correlation_id,
            start_time=req.start_time,
            end_time=req.end_time,
            write_explanation=bool(req.write_explanation),
            explanation_collection=str(req.explanation_collection or "strategy_explanations"),
        )
    except Exception as e:
        logger.exception("scalper_observer.explain_failed")
        raise HTTPException(status_code=500, detail={"error": "explain_failed", "message": str(e)}) from e


@app.get("/explain", response_model=StrategyExplanation)
async def explain_get(
    signal_id: Optional[str] = Query(default=None),
    correlation_id: Optional[str] = Query(default=None),
    start_time: Optional[str] = Query(default=None),
    end_time: Optional[str] = Query(default=None),
    write_explanation: bool = Query(default=False),
    explanation_collection: Optional[str] = Query(default=None),
) -> StrategyExplanation:
    return await explain(
        ExplainRequest(
            signal_id=signal_id,
            correlation_id=correlation_id,
            start_time=start_time,
            end_time=end_time,
            write_explanation=write_explanation,
            explanation_collection=explanation_collection,
        )
    )


@app.get("/ops/health")
async def ops_health() -> dict[str, Any]:
    return {"status": "ok", "service": _service_name(), "ts": datetime.now(timezone.utc).isoformat()}


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

