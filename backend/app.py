from __future__ import annotations

from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="marketdata-mcp-server")

import asyncio
import os
import time
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from backend.common.agent_boot import configure_startup_logging
from backend.common.http_correlation import install_http_correlation
from backend.common.ops_metrics import (
    REGISTRY,
    agent_start_total,
    errors_total,
    mark_activity,
    update_marketdata_heartbeat_metrics,
)

from backend.observability.correlation import install_fastapi_correlation_middleware

from backend.common.marketdata_heartbeat import snapshot
from backend.observability.correlation import install_fastapi_correlation_middleware
from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main
from backend.streams.alpaca_quotes_streamer import (
    LAST_MARKETDATA_SOURCE,
    get_last_marketdata_ts,
)
from backend.safety.config import load_kill_switch, load_stale_threshold_seconds
from backend.safety.safety_state import evaluate_safety_state, is_safe_to_run_strategies

app = FastAPI()
install_fastapi_correlation_middleware(app)
install_http_correlation(app, service="marketdata-mcp-server")


def _service_name() -> str:
    return str(os.getenv("SERVICE_NAME") or "marketdata-mcp-server")

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
async def startup_event() -> None:
    configure_startup_logging(
        agent_name="marketdata-mcp-server",
        intent="Serve marketdata MCP endpoints and run the Alpaca streamer background task.",
    )
    agent_start_total.inc(labels={"component": "marketdata-mcp-server"})
    # Mark activity at startup so heartbeat_age_seconds starts at ~0.
    mark_activity("marketdata")
    app.state.shutting_down = False
    app.state.ready = False
    app.state.loop_heartbeat_monotonic = time.monotonic()

    async def _loop_heartbeat() -> None:
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
            await asyncio.sleep(1.0)

    app.state.loop_task = asyncio.create_task(_loop_heartbeat())

    print("Starting Alpaca streamer...", flush=True)
    stream_task: asyncio.Task = asyncio.create_task(alpaca_streamer_main())
    app.state.stream_task = stream_task

    def _done_callback(t: asyncio.Task) -> None:
        try:
            t.result()
        except Exception as e:  # pragma: no cover
            # Surface background streamer failures (and count them) instead of failing silently.
            errors_total.inc(labels={"component": "marketdata-mcp-server"})
            print(f"[marketdata-mcp-server] alpaca_streamer_task_failed: {type(e).__name__}: {e}", flush=True)

    stream_task.add_done_callback(_done_callback)

    # Mark readiness once the background task is scheduled and the loop is running.
    # NOTE: We avoid tying readiness to "market open" / tick arrival to prevent flapping.
    await asyncio.sleep(0)
    app.state.ready = True
    print(f"SERVICE_READY: {_service_name()}", flush=True)

@app.on_event("shutdown")
async def shutdown_event() -> None:
    app.state.shutting_down = True
    try:
        print(f"shutdown_intent service={_service_name()}", flush=True)
    except Exception:
        pass

    # Stop background tasks.
    stream_task: asyncio.Task | None = getattr(app.state, "stream_task", None)
    loop_task: asyncio.Task | None = getattr(app.state, "loop_task", None)

    for t in (stream_task, loop_task):
        if t is None:
            continue
        try:
            t.cancel()
        except Exception:
            pass

    for t in (stream_task, loop_task):
        if t is None:
            continue
        try:
            await t
        except Exception:
            pass

@app.get("/")
async def read_root():
    return {"message": "Alpaca Market Streamer is running"}

@app.get("/livez")
async def livez() -> dict[str, Any]:
    # Liveness should not flap on kill-switch or stale marketdata.
    return {"status": "alive", "identity": _identity()}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Health is best-effort; readiness uses /readyz.
    _, payload = _status_payload()
    return payload


@app.get("/readyz")
async def readyz() -> dict[str, Any]:
    # Readiness should not trigger restarts; expose state in payload instead.
    _, payload = _status_payload()
    return payload


@app.get("/health")
async def health_check():
    # Back-compat endpoint (intentionally does NOT gate readiness).
    return {"status": "healthy", "service_id": "agenttrader-prod-streamer"}

@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Process is alive.
    return {"status": "ok", "service": _service_name(), "identity": _identity()}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    # Dependencies initialized (background streamer scheduled).
    ready = bool(getattr(app.state, "ready", False))
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    stream_task: asyncio.Task | None = getattr(app.state, "stream_task", None)
    stream_ok = stream_task is not None and (not stream_task.done())
    ok = ready and stream_ok and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "not_ready", "service": _service_name(), "identity": _identity()}


@app.get("/livez")
async def livez(response: Response) -> dict[str, Any]:
    # Event loop not wedged (heartbeat task is running).
    now = time.monotonic()
    last = float(getattr(app.state, "loop_heartbeat_monotonic", 0.0) or 0.0)
    max_age_s = float(os.getenv("LIVEZ_MAX_AGE_S") or "5")
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    stream_task: asyncio.Task | None = getattr(app.state, "stream_task", None)
    stream_ok = stream_task is not None and (not stream_task.done())
    loop_ok = (now - last) <= max_age_s
    ok = loop_ok and (not shutting_down) and stream_ok
    response.status_code = 200 if ok else 503
    return {
        "status": "alive" if ok else ("stream_dead" if not stream_ok else "wedged"),
        "service": _service_name(),
        "loop_heartbeat_age_s": max(0.0, now - last),
        "max_age_s": max_age_s,
        "stream_task_alive": bool(stream_ok),
    }


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


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
