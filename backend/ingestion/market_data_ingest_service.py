from __future__ import annotations

from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import asyncio
import json
import logging
import os
import time
from typing import Any

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import Response

from backend.common.agent_boot import configure_startup_logging
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.logging import init_structured_logging, install_fastapi_request_id_middleware
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.observability.ops_json_logger import OpsLogger
from backend.common.kill_switch import get_kill_switch_state
from backend.common.ops_metrics import REGISTRY
from backend.ops.status_contract import AgentIdentity, EndpointsBlock, build_ops_status
from backend.ingestion.market_data_ingest import (
    MarketDataIngestor,
    load_config_from_env,
    log_json,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AgentTrader Market Ingestion Service")
init_structured_logging(service="market-ingest")
install_fastapi_request_id_middleware(app, service="market-ingest")


@app.get("/health")
async def health() -> dict[str, Any]:
    ingestor: MarketDataIngestor | None = getattr(app.state, "ingestor", None)
    stats = ingestor.stats.__dict__ if ingestor is not None else None
    return {"status": "ok", "service": "market-ingest", "stats": stats, **get_build_fingerprint()}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Alias for institutional conventions.
    return await health()

@app.get("/ops/health")
async def ops_health() -> dict[str, Any]:
    return {"status": "ok", "service": "market-ingest", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/readyz")
async def readyz(response) -> dict[str, Any]:
    ready = bool(getattr(app.state, "ready", False))
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    ingest_task: asyncio.Task | None = getattr(app.state, "ingest_task", None)
    ingest_ok = ingest_task is not None and (not ingest_task.done())
    ok = ready and ingest_ok and (not shutting_down)
    try:
        response.status_code = 200 if ok else 503
    except Exception:
        pass
    return {"status": "ok" if ok else "not_ready", "service": "market-ingest"}


@app.get("/livez")
async def livez(response) -> dict[str, Any]:
    now = time.monotonic()
    last = float(getattr(app.state, "loop_heartbeat_monotonic", 0.0) or 0.0)
    max_age_s = float(os.getenv("LIVEZ_MAX_AGE_S") or "5")
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    ingest_task: asyncio.Task | None = getattr(app.state, "ingest_task", None)
    ingest_ok = ingest_task is not None and (not ingest_task.done())
    loop_ok = (now - last) <= max_age_s
    ok = loop_ok and ingest_ok and (not shutting_down)
    try:
        response.status_code = 200 if ok else 503
    except Exception:
        pass
    return {
        "status": "alive" if ok else ("ingest_dead" if not ingest_ok else "wedged"),
        "service": "market-ingest",
        "loop_heartbeat_age_s": max(0.0, now - last),
        "max_age_s": max_age_s,
    }


@app.on_event("startup")
async def _startup() -> None:
    """
    Cloud Run Service entrypoint.

    Cloud Run requires a listening HTTP server; ingestion runs as a background task
    while this FastAPI app provides health checks.
    """
    enforce_agent_mode_guard()

    configure_startup_logging(
        agent_name="market-ingest-service",
        intent="Run market quote ingestion in background while serving health checks (Cloud Run service).",
    )
    app.state.ops_logger = OpsLogger("market-ingest")
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        pass

    cfg = load_config_from_env()

    # Deterministic Alpaca auth smoke tests (startup gate).
    # If these fail, crash the container so Cloud Run/K8s restarts it.
    if (
        (not cfg.dry_run)
        and os.getenv("SKIP_ALPACA_AUTH_SMOKE_TESTS", "").strip().lower() not in ("1", "true", "yes", "y")
    ):
        try:
            from backend.streams.alpaca_auth_smoke import run_alpaca_auth_smoke_tests_async  # noqa: WPS433

            feed = getattr(cfg.feed, "value", None) or "iex"
            timeout_s = float(os.getenv("ALPACA_AUTH_SMOKE_TIMEOUT_S", "5"))
            log_json("alpaca_auth_smoke", status="starting", feed=str(feed), timeout_s=timeout_s)
            await run_alpaca_auth_smoke_tests_async(feed=str(feed), timeout_s=timeout_s)
            log_json("alpaca_auth_smoke", status="ok", feed=str(feed))
        except Exception as e:
            log_json("alpaca_auth_smoke", status="error", error=str(e), severity="ERROR")
            raise

    ingestor = MarketDataIngestor(cfg)
    app.state.ingestor = ingestor
    app.state.shutting_down = False
    app.state.ready = False
    app.state.loop_heartbeat_monotonic = time.monotonic()

    async def _loop_heartbeat() -> None:
        last_ops_log = 0.0
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
            now = time.monotonic()
            if (now - last_ops_log) >= float(os.getenv("OPS_HEARTBEAT_LOG_INTERVAL_S") or "60"):
                last_ops_log = now
                try:
                    app.state.ops_logger.heartbeat(kind="loop")  # type: ignore[attr-defined]
                except Exception:
                    pass
            await asyncio.sleep(1.0)

    app.state.loop_task = asyncio.create_task(_loop_heartbeat())

    async def _run() -> None:
        log_json("service_startup", status="ok")
        try:
            await ingestor.run()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("market_ingest_service.crashed: %s", e)
            # Let the container crash so Cloud Run restarts it.
            raise

    app.state.ingest_task = asyncio.create_task(_run())
    await asyncio.sleep(0)
    app.state.ready = True
    try:
        app.state.ops_logger.readiness(ready=True)  # type: ignore[attr-defined]
    except Exception:
        pass


@app.on_event("shutdown")
async def _shutdown() -> None:
    app.state.shutting_down = True
    try:
        app.state.ops_logger.shutdown(phase="initiated")  # type: ignore[attr-defined]
    except Exception:
        pass
    ingestor: MarketDataIngestor | None = getattr(app.state, "ingestor", None)
    task: asyncio.Task | None = getattr(app.state, "ingest_task", None)
    loop_task: asyncio.Task | None = getattr(app.state, "loop_task", None)

    try:
        if ingestor is not None:
            ingestor.request_stop()
    except Exception:
        pass

    if task is not None:
        task.cancel()
        try:
            await task
        except Exception:
            pass

    if loop_task is not None:
        loop_task.cancel()
        try:
            await loop_task
        except Exception:
            pass


@app.get("/ops/status")
async def ops_status() -> dict[str, Any]:
    """
    Stable ops status contract.
    """
    kill, _source = get_kill_switch_state()
    st = build_ops_status(
        service_name="market-ingest",
        service_kind="ingest",
        agent_identity=AgentIdentity(
            agent_name=str(os.getenv("AGENT_NAME") or "market-ingest"),
            agent_role=str(os.getenv("AGENT_ROLE") or "ingest"),
            agent_mode=str(os.getenv("AGENT_MODE") or "SERVICE"),
        ),
        git_sha=os.getenv("GIT_SHA") or os.getenv("K_REVISION") or None,
        build_id=os.getenv("BUILD_ID") or None,
        kill_switch=bool(kill),
        heartbeat_ttl_seconds=int(os.getenv("OPS_HEARTBEAT_TTL_S") or "60"),
        endpoints=EndpointsBlock(healthz="/healthz", heartbeat=None, metrics="/metrics"),
    )
    return st.model_dump()


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=REGISTRY.render_prometheus_text(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/ops/metrics")
async def ops_metrics() -> Response:
    return await metrics()

