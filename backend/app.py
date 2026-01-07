import uvicorn
from fastapi import FastAPI, Response
import asyncio
import os
from datetime import datetime, timezone
from typing import Any

from backend.common.agent_boot import configure_startup_logging

from backend.common.marketdata_heartbeat import snapshot
from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main
from backend.streams.alpaca_quotes_streamer import (
    LAST_MARKETDATA_SOURCE,
    get_last_marketdata_ts,
)
from backend.safety.config import load_kill_switch, load_stale_threshold_seconds
from backend.safety.safety_state import evaluate_safety_state, is_safe_to_run_strategies

app = FastAPI()

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
    print("Starting Alpaca streamer...")
    asyncio.create_task(alpaca_streamer_main())

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
    Marketdata freshness contract for downstream strategy evaluation loops.
    """
    kill = load_kill_switch()
    threshold = load_stale_threshold_seconds()
    last_ts = get_last_marketdata_ts()
    now = datetime.now(timezone.utc)

    stale = True
    age_s: float | None = None
    if last_ts is not None:
        ts = last_ts.replace(tzinfo=timezone.utc) if last_ts.tzinfo is None else last_ts.astimezone(timezone.utc)
        age_s = (now - ts).total_seconds()
        stale = age_s > float(threshold)

    status = "stale" if stale else "fresh"
    # Heartbeat should be readable even when kill-switch is enabled.
    response.status_code = 200
    return {
        "last_marketdata_ts": last_ts.isoformat() if last_ts else None,
        "source": LAST_MARKETDATA_SOURCE,
        "stale_threshold_seconds": threshold,
        "status": status,
        "age_seconds": age_s,
        "kill_switch": bool(kill),
    }


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, Any]:
    """
    Unified health status.
    - HTTP 200 only when status == ok
    - HTTP 503 when status == degraded or halted
    """
    status, payload = _status_payload()
    response.status_code = 200 if status == "ok" else 503
    return payload


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    """
    Readiness: only ready when status == ok.
    """
    status, payload = _status_payload()
    response.status_code = 200 if status == "ok" else 503
    return payload


@app.get("/livez")
async def livez() -> dict[str, Any]:
    """
    Liveness: process is alive (never fails due to market being halted/closed).
    """
    return {"status": "alive", "identity": _identity()}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)