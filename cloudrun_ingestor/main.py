from __future__ import annotations

"""
Cloud Run ingestor (minimal, import-safe service surface).

Test/CI requirements (see `tests/test_imports.py`, `tests/test_graceful_shutdown_cloudrun_ingestor.py`):
- Importing `cloudrun_ingestor.main` must succeed with dummy env vars set.
- The module must expose `app` (FastAPI) and `SHUTDOWN_FLAG` (threading.Event).
- SIGTERM must cause the process to exit promptly (shutdown smoke harness).

Production note:
- This module intentionally avoids Secret Manager access at import time.
"""

import logging
import os
import signal
import threading
from typing import Any

from fastapi import FastAPI

logger = logging.getLogger(__name__)

REQUIRED_ENV: tuple[str, ...] = (
    "GCP_PROJECT",
    "SYSTEM_EVENTS_TOPIC",
    "MARKET_TICKS_TOPIC",
    "MARKET_BARS_1M_TOPIC",
    "TRADE_SIGNALS_TOPIC",
    "INGEST_FLAG_SECRET_ID",
)


def _require_env(name: str) -> str:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        raise RuntimeError(f"Missing required env var: {name}")
    return str(v).strip()


def _validate_import_env() -> None:
    # Validate presence only (do not dereference secrets at import time).
    for k in REQUIRED_ENV:
        _require_env(k)


# Import-time validation (fail fast on missing env contract).
_validate_import_env()


SHUTDOWN_FLAG = threading.Event()


def _handle_shutdown(signum: int, _frame: Any | None = None) -> None:
    try:
        logger.info("shutdown_signal_received signum=%s", signum)
    except Exception:
        pass
    SHUTDOWN_FLAG.set()


signal.signal(signal.SIGTERM, _handle_shutdown)
signal.signal(signal.SIGINT, _handle_shutdown)


app = FastAPI(title="cloudrun-ingestor")


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "cloudrun-ingestor"}

