"""
cloudrun_ingestor entrypoint diagnostics

Runtime assumptions (documented for deploy/debug):
- The repository root (or the directory containing the `backend/` package) must
  be on `sys.path` so imports like `import backend...` resolve (commonly via
  `PYTHONPATH` in the container image or Cloud Run configuration).
- If `backend` imports fail, this process should fail fast with CRITICAL logs,
  because continuing would leave the service "up" but non-functional.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import threading
from typing import Any
from typing import NoReturn

def _normalize_env_alias(target: str, aliases: list[str]) -> None:
    """
    Ensure `target` is present by copying from first present alias.

    This never logs values (secrets-safe).
    """
    if (os.getenv(target) or "").strip():
        return
    for a in aliases:
        v = (os.getenv(a) or "").strip()
        if v:
            os.environ[target] = v
            return


def _missing_required_env(required: list[str]) -> list[str]:
    missing: list[str] = []
    for name in required:
        if not (os.getenv(name) or "").strip():
            missing.append(name)
    return missing


def _fail_fast(msg: str) -> NoReturn:
    logger.critical(msg, extra=LOG_EXTRA)
    raise RuntimeError(msg)


# --- Structured Logging & Pre-run Configuration ---
# This must run before any other modules are imported to ensure logging is configured correctly.

# Always initialize stdlib logging first.
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Only attempt google-cloud-logging setup on Cloud Run (avoid any GCP/ADC/network
# lookups during local runs and CI import checks).
if (os.getenv("K_SERVICE") or "").strip():
    try:
        import google.cloud.logging  # type: ignore

        logging_client = google.cloud.logging.Client()
        logging_client.setup_logging()
    except Exception as e:  # noqa: BLE001 - best-effort logging initialization
        logging.getLogger(__name__).warning(
            "google-cloud-logging unavailable; using std logging: %s",
            e,
        )

# Set up a logger adapter to inject custom static fields into all log messages.
LOG_EXTRA = {
    "service": os.getenv("K_SERVICE", "cloudrun_ingestor"),
    "env": os.getenv("ENV", "prod"),
}
logger = logging.getLogger(__name__)

def _bootstrap_env() -> None:
    # Allow existing CI/scripts to use either variable name.
    _normalize_env_alias("GCP_PROJECT", ["GCP_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", "GCP_PROJECT"])


_bootstrap_env()

# Validate presence only (no values).
_REQUIRED_ENV = [
    "GCP_PROJECT",
    "SYSTEM_EVENTS_TOPIC",
    "MARKET_TICKS_TOPIC",
    "MARKET_BARS_1M_TOPIC",
    "TRADE_SIGNALS_TOPIC",
    "INGEST_FLAG_SECRET_ID",
]
_missing = _missing_required_env(_REQUIRED_ENV)
if _missing:
    _fail_fast(f"Missing required environment variables: {', '.join(_missing)}")

# Canonical imports: ensure they resolve at startup.
try:
    import backend.ingestion.config as _config  # noqa: F401
    import backend.ingestion.publisher as _publisher  # noqa: F401
except Exception as e:
    _fail_fast(f"Failed to import canonical ingestion modules: {type(e).__name__}: {e}")

try:
    from backend.common.cloudrun_perf import identity_fields as _identity_fields  # noqa: WPS433
    from backend.common.cloudrun_perf import instance_uptime_ms as _instance_uptime_ms  # noqa: WPS433

    logger.info(
        "Cloud Run process start",
        extra={
            **LOG_EXTRA,
            "event_type": "cloudrun.process_start",
            "instance_uptime_ms": _instance_uptime_ms(),
            **_identity_fields(),
        },
    )
except Exception:
    pass


# --- Graceful Shutdown Handling ---
SHUTDOWN_FLAG = threading.Event()

def shutdown_handler(signum: int, frame: Any) -> None:
    """Sets the shutdown flag on receiving SIGTERM or SIGINT."""
    log_data = {**LOG_EXTRA, "signal": signal.Signals(signum).name}
    logger.warning("Shutdown signal received. Exiting main loop.", extra=log_data)
    SHUTDOWN_FLAG.set()


# Register the shutdown handler
signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


# --- Background Worker for Ingestion Loop ---
def ingestion_worker() -> None:
    """
    Background worker.

    Keep this import-safe (no network/GCP calls) so CI can import `main:app`.
    Production ingestion behavior is implemented elsewhere; this thread is a
    placeholder that keeps the Cloud Run container's process model stable.
    """
    logger.info("Ingestion worker thread started.", extra={**LOG_EXTRA, "event_type": "cloudrun.worker.start"})
    # Wait until shutdown. No work here by design.
    SHUTDOWN_FLAG.wait()
    logger.warning("Ingestion worker shutting down.", extra={**LOG_EXTRA, "event_type": "cloudrun.worker.shutdown"})


# --- Flask App for Gunicorn ---
# A minimal Flask app is required for Gunicorn to have a process to manage.
# The actual work is done in the background thread.
try:
    from flask import Flask
except Exception as e:
    _fail_fast(f"Failed to import Flask: {type(e).__name__}: {e}")
app = Flask(__name__)

try:
    from backend.common.cloudrun_perf import classify_request as _classify_request  # noqa: WPS433

    @app.before_request
    def _cloudrun_request_perf_hook():  # type: ignore[no-redef]
        # Minimal noise: still logs once per request (health checks are low-QPS here).
        c = _classify_request()
        logger.info(
            "Request handled",
            extra={
                **LOG_EXTRA,
                "event_type": "cloudrun.http_request",
                "cold_start": bool(c.cold_start),
                "request_ordinal": int(c.request_ordinal),
                "instance_uptime_ms": int(c.instance_uptime_ms),
            },
        )

except Exception:
    pass

@app.route("/")
def index():
    # This endpoint is not strictly necessary for the worker but is useful for health checks.
    return "Ingestion service is running.", 200

# Start the background worker thread when the Flask app initializes.
if (os.getenv("CLOUDRUN_INGESTOR_START_WORKER") or "1").strip().lower() not in {"0", "false", "no"}:
    worker_thread = threading.Thread(target=ingestion_worker, daemon=True)
    worker_thread.start()
