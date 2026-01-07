from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from fastapi import FastAPI

from backend.common.agent_boot import configure_startup_logging
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.ingestion.market_data_ingest import (
    MarketDataIngestor,
    load_config_from_env,
    log_json,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AgentTrader Market Ingestion Service")


@app.get("/health")
async def health() -> dict[str, Any]:
    ingestor: MarketDataIngestor | None = getattr(app.state, "ingestor", None)
    stats = ingestor.stats.__dict__ if ingestor is not None else None
    return {"status": "ok", "service": "market-ingest", "stats": stats, **get_build_fingerprint()}


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    # Alias for institutional conventions.
    return await health()


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


@app.on_event("shutdown")
async def _shutdown() -> None:
    ingestor: MarketDataIngestor | None = getattr(app.state, "ingestor", None)
    task: asyncio.Task | None = getattr(app.state, "ingest_task", None)

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

