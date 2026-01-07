import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
import asyncio
import sys
import os

from backend.common.agent_boot import configure_startup_logging
from backend.common.ops_metrics import (
    REGISTRY,
    agent_start_total,
    errors_total,
    mark_activity,
    update_marketdata_heartbeat_metrics,
)

from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    configure_startup_logging(
        agent_name="marketdata-mcp-server",
        intent="Serve marketdata MCP endpoints and run the Alpaca streamer background task.",
    )
    agent_start_total.inc(labels={"component": "marketdata-mcp-server"})
    # Mark activity at startup so heartbeat_age_seconds starts at ~0.
    mark_activity("marketdata")
    print("Starting Alpaca streamer...")
    task = asyncio.create_task(alpaca_streamer_main())

    def _done_callback(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception as e:  # pragma: no cover
            # Surface background streamer failures (and count them) instead of failing silently.
            errors_total.inc(labels={"component": "marketdata-mcp-server"})
            print(f"[marketdata-mcp-server] alpaca_streamer_task_failed: {type(e).__name__}: {e}", flush=True)

    task.add_done_callback(_done_callback)

@app.get("/")
async def read_root():
    return {"message": "Alpaca Market Streamer is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service_id": "agenttrader-prod-streamer"}

@app.get("/ops/status")
async def ops_status():
    """
    Lightweight ops endpoint for SLOs and quick checks.
    """
    stale_s = float(os.getenv("MARKETDATA_STALE_THRESHOLD_S", "120"))
    hb = update_marketdata_heartbeat_metrics(stale_threshold_s=stale_s)
    return {
        "status": "ok",
        "service": "marketdata-mcp-server",
        "heartbeat": hb,
    }


@app.get("/metrics")
async def metrics():
    """
    Prometheus text exposition format.
    """
    stale_s = float(os.getenv("MARKETDATA_STALE_THRESHOLD_S", "120"))
    # Update derived heartbeat metrics right before rendering.
    update_marketdata_heartbeat_metrics(stale_threshold_s=stale_s)
    return Response(
        content=REGISTRY.render_prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)