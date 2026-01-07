import os
import logging
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import strategies, broker_accounts, paper_orders, trades

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state
from backend.execution.marketdata_health import check_market_ingest_heartbeat
from backend.ops.status_contract import AgentIdentity, EndpointsBlock, build_ops_status

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

@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "strategy-service"}


@app.get("/ops/status")
def ops_status() -> dict[str, Any]:
    kill, _source = get_kill_switch_state()
    tenant_id = str(os.getenv("TENANT_ID") or os.getenv("STRATEGY_TENANT_ID") or "").strip() or None
    stale_s = int(os.getenv("MARKETDATA_STALE_THRESHOLD_S") or "120")
    hb = check_market_ingest_heartbeat(tenant_id=tenant_id, stale_threshold_seconds=stale_s)

    st = build_ops_status(
        service_name="strategy-engine",
        service_kind="strategy",
        agent_identity=AgentIdentity(
            agent_name=str(os.getenv("AGENT_NAME") or "strategy-engine"),
            agent_role=str(os.getenv("AGENT_ROLE") or "strategy"),
            agent_mode=str(os.getenv("AGENT_MODE") or "SERVICE"),
        ),
        git_sha=os.getenv("GIT_SHA") or os.getenv("K_REVISION") or None,
        build_id=os.getenv("BUILD_ID") or None,
        kill_switch=bool(kill),
        heartbeat_ttl_seconds=int(os.getenv("OPS_HEARTBEAT_TTL_S") or "60"),
        marketdata_last_tick_utc=hb.last_heartbeat_at,
        marketdata_stale_threshold_seconds=stale_s,
        endpoints=EndpointsBlock(healthz="/health", heartbeat=None, metrics=None),
    )
    return st.model_dump()

# Include institutional analytics router
try:
    from backend.analytics.institutional_api import router as institutional_router
    app.include_router(institutional_router)
except Exception as e:
    print(f"Warning: Could not load institutional analytics router: {e}")
