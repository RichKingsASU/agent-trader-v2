import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import strategies, broker_accounts, paper_orders, trades

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state
from backend.common.http_correlation import install_http_correlation

app = FastAPI(title="AgentTrader Strategy Service")
install_fastapi_correlation_middleware(app)

install_http_correlation(app, service="strategy-service")

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

@app.on_event("startup")
def _startup() -> None:
    # Startup identity/intent log (single JSON line).
    configure_startup_logging(
        agent_name="strategy-service",
        intent="Serve strategy management APIs (strategies, broker accounts, paper orders, trades).",
    )
    enabled, source = get_kill_switch_state()
    if enabled:
        # Non-execution service: keep serving, but make it visible in logs.
        logger.warning("kill_switch_active enabled=true source=%s", source)

@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "strategy-service"}

@app.get("/ops/status")
def ops_status() -> dict[str, Any]:
    kill, _source = get_kill_switch_state()
    tenant_id = str(os.getenv("TENANT_ID") or os.getenv("STRATEGY_TENANT_ID") or "").strip() or None
    stale_s = int(os.getenv("MARKETDATA_STALE_THRESHOLD_S") or "120")
    hb = check_market_ingest_heartbeat(tenant_id=tenant_id, stale_threshold_seconds=stale_s)

@app.get("/healthz")
def healthz() -> dict:
    # readiness: if process is serving, it's "ready" (this service is non-execution).
    return {"ok": True, "service": "strategy-service"}


@app.get("/ops/status")
def ops_status() -> dict:
    enabled, source = get_kill_switch_state()
    return {
        "service": "strategy-service",
        "git_sha": (os.getenv("GIT_SHA") or os.getenv("COMMIT_SHA") or "unknown"),
        "build_id": (os.getenv("BUILD_ID") or "unknown"),
        "agent_mode": (os.getenv("AGENT_MODE") or "DISABLED"),
        "kill_switch_enabled": bool(enabled),
        "kill_switch_source": source,
    }

# Include institutional analytics router
try:
    from backend.analytics.institutional_api import router as institutional_router
    app.include_router(institutional_router)
except Exception as e:
    print(f"Warning: Could not load institutional analytics router: {e}")
