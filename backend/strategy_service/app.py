import os
import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import strategies, broker_accounts, paper_orders, trades

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state

app = FastAPI(title="AgentTrader Strategy Service")
install_fastapi_correlation_middleware(app)

# Startup identity/intent log (single JSON line).
@app.on_event("startup")
def _startup() -> None:
    configure_startup_logging(
        agent_name="strategy-service",
        intent="Serve strategy management APIs (strategies, broker accounts, paper orders, trades).",
    )
    enabled, source = get_kill_switch_state()
    if enabled:
        # Non-execution service: keep serving, but make it visible in logs.
        logger.warning("kill_switch_active enabled=true source=%s", source)

    enabled, source = get_kill_switch_state()
    if enabled:
        # Non-execution service: keep serving, but make it visible in logs.
        logger.warning("kill_switch_active enabled=true source=%s", source)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/ops/status")
def ops_status() -> dict[str, str]:
    return {"status": "ok", "service": "strategy-service"}

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(strategies.router)
app.include_router(broker_accounts.router)
app.include_router(paper_orders.router)
app.include_router(trades.router)

# Include institutional analytics router
try:
    from backend.analytics.institutional_api import router as institutional_router
    app.include_router(institutional_router)
except Exception as e:
    print(f"Warning: Could not load institutional analytics router: {e}")
