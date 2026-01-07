import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import strategies, broker_accounts, paper_orders, trades, strategy_configs

from backend.common.kill_switch import get_kill_switch_state
from backend.common.agent_boot import configure_startup_logging
from backend.strategies.registry.loader import load_all_configs

app = FastAPI(title="AgentTrader Strategy Service")
install_fastapi_correlation_middleware(app)

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
app.include_router(strategy_configs.router)

@app.on_event("startup")
def _startup() -> None:
    # Identity/intent log (single JSON line).
    configure_startup_logging(
        agent_name="strategy-service",
        intent="Serve strategy management APIs + read-only strategy config registry endpoints.",
    )

    # Load registry at startup so we fail-fast on invalid/duplicate configs.
    app.state.strategy_config_registry = load_all_configs()

    enabled, source = get_kill_switch_state()
    if enabled:
        # Non-execution service: keep serving, but make it visible in logs.
        logger.warning("kill_switch_active enabled=true source=%s", source)

# Include institutional analytics router
try:
    from backend.analytics.institutional_api import router as institutional_router
    app.include_router(institutional_router)
except Exception as e:
    print(f"Warning: Could not load institutional analytics router: {e}")
