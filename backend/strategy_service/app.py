from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="strategy-service")
del _log_runtime_fingerprint

from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="strategy-service")

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from .routers import strategies, broker_accounts, paper_orders, trades, strategy_configs

from backend.common.kill_switch import get_kill_switch_state
from backend.common.agent_boot import configure_startup_logging
from backend.observability.correlation import install_fastapi_correlation_middleware
from backend.strategies.registry.loader import load_all_configs

app = FastAPI(title="AgentTrader Strategy Service")
install_fastapi_correlation_middleware(app)

logger = logging.getLogger(__name__)

def _service_name() -> str:
    # Allow k8s to override to per-strategy workload names.
    return str(os.getenv("SERVICE_NAME") or os.getenv("AGENT_NAME") or "strategy-service")

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
async def _startup() -> None:
    # Identity/intent log (single JSON line).
    configure_startup_logging(
        agent_name="strategy-service",
        intent="Serve strategy management APIs + read-only strategy config registry endpoints.",
    )

    # Load registry at startup so we fail-fast on invalid/duplicate configs.
    app.state.strategy_config_registry = load_all_configs()

    app.state.shutting_down = False
    app.state.loop_heartbeat_monotonic = time.monotonic()

    async def _loop_heartbeat() -> None:
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
            await asyncio.sleep(1.0)

    app.state.loop_task = asyncio.create_task(_loop_heartbeat())

    enabled, source = get_kill_switch_state()
    if enabled:
        # Non-execution service: keep serving, but make it visible in logs.
        logger.warning("kill_switch_active enabled=true source=%s", source)

    # Readiness becomes true after registry load + loop heartbeat started.
    app.state.ready = True
    print(f"SERVICE_READY: {_service_name()}", flush=True)


@app.on_event("shutdown")
async def _shutdown() -> None:
    app.state.shutting_down = True
    try:
        print(f"shutdown_intent service={_service_name()}", flush=True)
    except Exception:
        pass
    loop_task: asyncio.Task | None = getattr(app.state, "loop_task", None)
    if loop_task is not None:
        loop_task.cancel()
        try:
            await loop_task
        except Exception:
            pass


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Process is alive.
    return {"status": "ok", "service": _service_name()}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    ready = bool(getattr(app.state, "ready", False))
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    ok = ready and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "not_ready", "service": _service_name()}


@app.get("/livez")
async def livez(response: Response) -> dict[str, Any]:
    now = time.monotonic()
    last = float(getattr(app.state, "loop_heartbeat_monotonic", 0.0) or 0.0)
    max_age_s = float(os.getenv("LIVEZ_MAX_AGE_S") or "5")
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    ok = (now - last) <= max_age_s and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {"status": "alive" if ok else "wedged", "service": _service_name(), "loop_heartbeat_age_s": max(0.0, now - last)}

# Include institutional analytics router
try:
    from backend.analytics.institutional_api import router as institutional_router
    app.include_router(institutional_router)
except Exception as e:
    print(f"Warning: Could not load institutional analytics router: {e}")
