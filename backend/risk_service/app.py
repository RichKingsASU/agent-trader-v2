from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="risk-service")
del _log_runtime_fingerprint

import json

from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

from fastapi import FastAPI
from .routers import risk_limits

from backend.common.agent_boot import configure_startup_logging
from backend.observability.correlation import install_fastapi_correlation_middleware

app = FastAPI(title="AgentTrader Risk Service")
install_fastapi_correlation_middleware(app)

@app.on_event("startup")
def _startup() -> None:
    configure_startup_logging(
        agent_name="risk-service",
        intent="Serve risk APIs (limits/checks) for strategy execution.",
    )
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
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
