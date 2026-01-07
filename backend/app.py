from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from backend.common.agent_boot import configure_startup_logging
from backend.common.ops_metrics import (
    REGISTRY,
    agent_start_total,
    errors_total,
    mark_activity,
    update_marketdata_heartbeat_metrics,
)

from backend.common.marketdata_heartbeat import snapshot
from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main
from backend.streams.alpaca_quotes_streamer import (
    LAST_MARKETDATA_SOURCE,
    get_last_marketdata_ts,
)
from backend.safety.config import load_kill_switch, load_stale_threshold_seconds
from backend.safety.safety_state import evaluate_safety_state, is_safe_to_run_strategies

app = FastAPI()
install_fastapi_correlation_middleware(app)

def _identity() -> dict[str, Any]:
    return {
        "agent_name": "marketdata-mcp-server",
        "workload": os.getenv("WORKLOAD") or None,
        "git_sha": os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        "environment": os.getenv("ENVIRONMENT") or os.getenv("ENV") or None,
    }


def _status_payload() -> tuple[str, dict[str, Any]]:
    kill = load_kill_switch()
    threshold = load_stale_threshold_seconds()
    last_ts = get_last_marketdata_ts()

    state = evaluate_safety_state(
        trading_enabled=True,
        kill_switch=kill,
        marketdata_last_ts=last_ts,
        stale_threshold_seconds=threshold,
        ttl_seconds=30,
    )

    if kill:
        status = "halted"
    else:
        # marketdata-mcp-server health semantics:
        # - ok if receiving data within threshold
        # - degraded if stale/missing
        status = "ok" if (last_ts is not None and state.marketdata_fresh) else "degraded"

    payload = {
        "status": status,
        "identity": _identity(),
        "safety_state": {
            "trading_enabled": state.trading_enabled,
            "kill_switch": state.kill_switch,
            "marketdata_fresh": state.marketdata_fresh,
            "marketdata_last_ts": state.marketdata_last_ts.isoformat() if state.marketdata_last_ts else None,
            "reason_codes": state.reason_codes,
            "updated_at": state.updated_at.isoformat(),
            "ttl_seconds": state.ttl_seconds,
            "stale_threshold_seconds": threshold,
        },
        "last_marketdata_ts": last_ts.isoformat() if last_ts else None,
    }
    return status, payload


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

install_http_correlation(app, service="marketdata-mcp-server")

@app.get("/")
async def read_root():
    return {"message": "Alpaca Market Streamer is running"}

@app.get("/health")
async def health_check():
    # Back-compat endpoint (intentionally does NOT gate readiness).
    return {"status": "healthy", "service_id": "agenttrader-prod-streamer"}


@app.get("/heartbeat")
async def heartbeat(response: Response) -> dict[str, Any]:
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
