from __future__ import annotations

from backend.common.runtime_fingerprint import log_runtime_fingerprint as _log_runtime_fingerprint

_log_runtime_fingerprint(service="market-ingest")

import asyncio
import json
import logging
import os
import time
from typing import Any

from fastapi import FastAPI

from backend.common.agent_boot import configure_startup_logging
from backend.observability.correlation import install_fastapi_correlation_middleware
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.ingestion.market_data_ingest import (
    MarketDataIngestor,
    load_config_from_env,
    log_json,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AgentTrader Market Ingestion Service")
install_fastapi_correlation_middleware(app)


@app.get("/health")
async def health() -> dict[str, Any]:
    ingestor: MarketDataIngestor | None = getattr(app.state, "ingestor", None)
    stats = ingestor.stats.__dict__ if ingestor is not None else None
    return {"status": "ok", "service": "market-ingest", "stats": stats, **get_build_fingerprint()}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Alias for institutional conventions.
    return await health()


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
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    configure_startup_logging(
        agent_name="market-ingest-service",
        intent="Run market quote ingestion in background while serving health checks (Cloud Run service).",
    )
    try:
        fp = get_build_fingerprint()
        print(
            json.dumps({"intent_type": "build_fingerprint", **fp}, separators=(",", ":"), ensure_ascii=False),
            flush=True,
        )
    except Exception:
        pass

    cfg = load_config_from_env()
    ingestor = MarketDataIngestor(cfg)
    app.state.ingestor = ingestor
    app.state.shutting_down = False
    app.state.ready = False
    app.state.loop_heartbeat_monotonic = time.monotonic()

    async def _loop_heartbeat() -> None:
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
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
    print("SERVICE_READY: market-ingest", flush=True)


@app.on_event("shutdown")
async def _shutdown() -> None:
    app.state.shutting_down = True
    try:
        print("SHUTDOWN_INITIATED: market-ingest", flush=True)
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

