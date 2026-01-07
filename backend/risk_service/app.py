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

app.include_router(risk_limits.router)
