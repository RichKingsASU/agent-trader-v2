import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
import os
import json

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state
from backend.common.http_correlation import install_http_correlation

from backend.common.marketdata_heartbeat import snapshot
from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main

app = FastAPI()
install_fastapi_correlation_middleware(app)

@app.on_event("startup")
async def startup_event():
    configure_startup_logging(
        agent_name="marketdata-mcp-server",
        intent="Serve marketdata MCP endpoints and run the Alpaca streamer background task.",
    )
    enabled, source = get_kill_switch_state()
    if enabled:
        # Non-execution service: keep serving, but make it visible.
        print(f"kill_switch_active enabled=true source={source}", flush=True)
    print("Starting Alpaca streamer...")
    asyncio.create_task(alpaca_streamer_main())

install_http_correlation(app, service="marketdata-mcp-server")

@app.get("/")
async def read_root():
    return {"message": "Alpaca Market Streamer is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service_id": "agenttrader-prod-streamer", **get_build_fingerprint()}


@app.get("/healthz")
async def healthz_check():
    # Alias for institutional conventions.
    return await health_check()

@app.get("/healthz")
async def healthz():
    # Alias for Kubernetes probes.
    return await health_check()

@app.get("/readyz")
async def readyz():
    # Readiness is the same as health for this service (no external deps required).
    return {"status": "ok"}

@app.get("/ops/status")
async def ops_status():
    return {"status": "ok", "service": "marketdata-mcp-server"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)
