from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="risk-service")

from backend.common.logging import init_structured_logging, install_fastapi_request_id_middleware

init_structured_logging(service="risk-service")

import json
import logging

from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

from fastapi import FastAPI
from .routers import risk_limits

from backend.common.agent_boot import configure_startup_logging
from backend.common.app_heartbeat_writer import install_app_heartbeat
from backend.observability.build_fingerprint import get_build_fingerprint

app = FastAPI(title="AgentTrader Risk Service")
install_fastapi_request_id_middleware(app, service="risk-service")
install_app_heartbeat(app, service_name="risk-service")

logger = logging.getLogger(__name__)

@app.on_event("startup")
def _startup() -> None:
    _enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="risk-service",
        intent="Serve risk APIs (limits/checks) for strategy execution.",
    )
    try:
        fp = get_build_fingerprint()
        logger.info(
            "build_fingerprint",
            extra={
                "event_type": "build_fingerprint",
                "intent_type": "build_fingerprint",
                "service": "risk-service",
                **fp,
            },
        )
    except Exception:
        pass


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "risk-service", **get_build_fingerprint()}


@app.get("/healthz")
def healthz() -> dict:
    return health()

app.include_router(risk_limits.router)
