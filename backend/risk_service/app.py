import json
from fastapi import FastAPI
from .routers import risk_limits

from backend.common.agent_boot import configure_startup_logging
from backend.observability.build_fingerprint import get_build_fingerprint

app = FastAPI(title="AgentTrader Risk Service")

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
