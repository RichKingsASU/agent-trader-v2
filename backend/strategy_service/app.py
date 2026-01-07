import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .routers import strategies, broker_accounts, paper_orders, trades

from backend.common.agent_boot import configure_startup_logging
from backend.observability.build_fingerprint import get_build_fingerprint

app = FastAPI(title="AgentTrader Strategy Service")

# Startup identity/intent log (single JSON line).
@app.on_event("startup")
def _startup() -> None:
    configure_startup_logging(
        agent_name="strategy-service",
        intent="Serve strategy management APIs (strategies, broker accounts, paper orders, trades).",
    )
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        pass

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

# Health endpoints (keep lightweight; no DB calls).
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "strategy-service", **get_build_fingerprint()}


@app.get("/healthz")
def healthz() -> dict:
    return health()

# Include institutional analytics router
try:
    from backend.analytics.institutional_api import router as institutional_router
    app.include_router(institutional_router)
except Exception as e:
    print(f"Warning: Could not load institutional analytics router: {e}")
