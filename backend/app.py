from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from backend.common.agent_boot import configure_startup_logging
from backend.common.http_correlation import install_http_correlation
from backend.common.ops_metrics import REGISTRY, agent_start_total, errors_total, mark_activity, update_marketdata_heartbeat_metrics
from backend.streams.alpaca_quotes_streamer import main as alpaca_streamer_main
from backend.observability.correlation import install_fastapi_correlation_middleware

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
    app.state.ready_logged = False
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
    if stream_task.done():
        # Don't claim readiness if the streamer failed immediately.
        return
    app.state.ready = True
    if not bool(getattr(app.state, "ready_logged", False)):
        app.state.ready_logged = True
        print("SERVICE_READY: marketdata-mcp-server", flush=True)


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
async def read_root() -> dict[str, Any]:
    return {"message": "Alpaca Market Streamer is running"}

@app.get("/health")
async def health_check() -> dict[str, Any]:
    # Back-compat endpoint (intentionally does NOT gate readiness).
    return {"status": "healthy", "service_id": "agenttrader-prod-streamer"}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Process is alive (do not gate on external dependencies).
    return {"status": "ok", "service": _service_name(), "identity": _identity()}


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


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    # Dependencies initialized (background streamer scheduled and still alive).
    ready = bool(getattr(app.state, "ready", False))
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    stream_task: asyncio.Task | None = getattr(app.state, "stream_task", None)
    stream_ok = stream_task is not None and (not stream_task.done())
    ok = ready and stream_ok and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {
        "status": "ok" if ok else "not_ready",
        "service": _service_name(),
        "identity": _identity(),
        "ready": bool(ready),
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
