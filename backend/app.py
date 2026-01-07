import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
import os
import json

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state
from backend.ops.status_contract import AgentIdentity, EndpointsBlock, build_ops_status

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
    log_event("marketdata_streamer_starting")
    asyncio.create_task(alpaca_streamer_main())

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
