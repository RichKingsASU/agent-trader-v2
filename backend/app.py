from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="marketdata-mcp-server")
del _log_runtime_fingerprint

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response

from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.app_heartbeat_writer import install_app_heartbeat
from backend.common.http_correlation import install_http_correlation
from backend.common.ops_metrics import REGISTRY, agent_start_total, errors_total, mark_activity, update_marketdata_heartbeat_metrics
from backend.streams.alpaca_quotes_streamer import get_last_marketdata_ts, main as alpaca_streamer_main
from backend.observability.correlation import install_fastapi_correlation_middleware
from backend.observability.ops_json_logger import OpsLogger
from backend.utils.session import get_market_session
from backend.ops.status_contract import AgentIdentity, EndpointsBlock, build_ops_status
from backend.common.kill_switch import get_kill_switch_state

app = FastAPI()
install_fastapi_correlation_middleware(app)
install_http_correlation(app, service="marketdata-mcp-server")
install_app_heartbeat(app, service_name="marketdata-mcp-server")


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
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="marketdata-mcp-server",
        intent="Serve marketdata MCP endpoints and run the Alpaca streamer background task.",
    )
    app.state.ops_logger = OpsLogger("marketdata-mcp-server")
    agent_start_total.inc(labels={"component": "marketdata-mcp-server"})
    # Mark activity at startup so heartbeat_age_seconds starts at ~0.
    mark_activity("marketdata")
    app.state.shutting_down = False
    app.state.ready = False
    app.state.ready_logged = False
    app.state.started_at_utc = datetime.now(timezone.utc)
    app.state.loop_heartbeat_monotonic = time.monotonic()

    async def _loop_heartbeat() -> None:
        last_ops_log = 0.0
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
            now = time.monotonic()
            # Rate-limit ops heartbeat logs (avoid spam).
            if (now - last_ops_log) >= float(os.getenv("OPS_HEARTBEAT_LOG_INTERVAL_S") or "60"):
                last_ops_log = now
                try:
                    app.state.ops_logger.heartbeat(kind="loop")  # type: ignore[attr-defined]
                except Exception:
                    pass
            await asyncio.sleep(1.0)

    app.state.loop_task = asyncio.create_task(_loop_heartbeat())

    # Readiness tracking: only become ready once the streamer has configured subscriptions.
    app.state.streamer_ready_event = asyncio.Event()

    try:
        app.state.ops_logger.event("starting_streamer", severity="INFO")  # type: ignore[attr-defined]
    except Exception:
        pass
    stream_task: asyncio.Task = asyncio.create_task(alpaca_streamer_main(app.state.streamer_ready_event))
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
        try:
            app.state.ops_logger.readiness(ready=True)  # type: ignore[attr-defined]
        except Exception:
            pass


@app.on_event("shutdown")
async def shutdown_event() -> None:
    app.state.shutting_down = True
    app.state.ready = False
    try:
        app.state.ops_logger.shutdown(phase="initiated")  # type: ignore[attr-defined]
    except Exception:
        pass

    # Stop background tasks.
    stream_task: asyncio.Task | None = getattr(app.state, "stream_task", None)
    loop_task: asyncio.Task | None = getattr(app.state, "loop_task", None)
    ready_task: asyncio.Task | None = getattr(app.state, "ready_task", None)

    for t in (ready_task, stream_task, loop_task):
        if t is None:
            continue
        try:
            t.cancel()
        except Exception:
            pass

    tasks = [t for t in (ready_task, stream_task, loop_task) if t is not None]
    if not tasks:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10.0)
    except Exception:
        # Best-effort; never hang shutdown.
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

@app.get("/ops/health")
async def ops_health() -> dict[str, Any]:
    return {"status": "ok", "service": _service_name(), "ts": datetime.now(timezone.utc).isoformat()}


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
    # Marketdata watchdog: if we stop receiving messages during market hours, fail liveness.
    stale_threshold_s = float(os.getenv("LIVEZ_MARKETDATA_STALE_S") or os.getenv("MARKETDATA_STALE_THRESHOLD_S") or "120")
    now_utc = datetime.now(timezone.utc)
    session = get_market_session(now_utc)
    last_msg = get_last_marketdata_ts() or getattr(app.state, "started_at_utc", now_utc)
    age_s = (now_utc - last_msg).total_seconds() if session != "CLOSED" else 0.0
    marketdata_ok = (session == "CLOSED") or (age_s <= stale_threshold_s)

    ok = loop_ok and (not shutting_down) and stream_ok and marketdata_ok
    response.status_code = 200 if ok else 503
    if ok:
        return {"status": "ok"}
    if not stream_ok:
        return {"status": "stream_dead"}
    if not loop_ok:
        return {"status": "wedged"}
    return {"status": "stale", "market_session": session, "age_seconds": age_s, "stale_threshold_seconds": stale_threshold_s}


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

@app.get("/ops/metrics")
async def ops_metrics():
    # Stable alias for ops scrapers.
    return await metrics()


@app.get("/ops/status")
async def ops_status() -> dict[str, Any]:
    """
    Stable ops status contract.
    """
    kill, _source = get_kill_switch_state()
    stale_s = int(float(os.getenv("MARKETDATA_STALE_THRESHOLD_S", "120")))
    last_tick = get_last_marketdata_ts()
    st = build_ops_status(
        service_name=_service_name(),
        service_kind="marketdata",
        agent_identity=AgentIdentity(
            agent_name=str(os.getenv("AGENT_NAME") or "marketdata-mcp-server"),
            agent_role=str(os.getenv("AGENT_ROLE") or "marketdata"),
            agent_mode=str(os.getenv("AGENT_MODE") or "STREAM"),
        ),
        git_sha=os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        build_id=os.getenv("BUILD_ID") or None,
        kill_switch=bool(kill),
        heartbeat_ttl_seconds=int(os.getenv("OPS_HEARTBEAT_TTL_S") or "60"),
        marketdata_last_tick_utc=last_tick,
        marketdata_last_bar_utc=None,
        marketdata_stale_threshold_seconds=stale_s,
        endpoints=EndpointsBlock(healthz="/healthz", heartbeat="/heartbeat", metrics="/metrics"),
    )
    return st.model_dump()


def main() -> None:
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
