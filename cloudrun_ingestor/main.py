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
import traceback
from typing import Any
from typing import NoReturn

from backend.common.logging import init_structured_logging
from backend.common.logging import log_standard_event

# --- Runtime detection helpers ---
def _running_under_gunicorn() -> bool:
    """
    Best-effort detection for "real" service runtime vs local import checks.

    We intentionally avoid relying on sys.path hacks or environment-specific flags.
    """
    try:
        if (os.getenv("GUNICORN_CMD_ARGS") or "").strip():
            return True
        argv0 = os.path.basename(sys.argv[0] or "")
        if "gunicorn" in argv0.lower():
            return True
    except Exception:
        return False
    return False


def _fail_fast_import(exc: BaseException, *, context: str, failed_import: str) -> None:
    """
    Crash the process in real runtime if a required import fails.

    During local/CI import smoke checks (not under gunicorn), we only log CRITICAL
    and allow import to succeed.
    """
    log_standard_event(
        logger,
        "import.failed",
        severity="CRITICAL",
        outcome="failure",
        context=str(context),
        failed_import=str(failed_import),
        error=str(exc),
        exception=traceback.format_exc()[-8000:],
    )
    if _running_under_gunicorn():
        raise SystemExit(1)


# --- Env normalization + validation (log presence, fail fast) ---
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
    log_standard_event(logger, "startup.failed", severity="CRITICAL", outcome="failure", message=str(msg))
    raise RuntimeError(msg)


# --- Structured Logging & Pre-run Configuration ---
# This must run before any other modules are imported to ensure logging is configured correctly.

# Emit structured JSON to stdout (Cloud Run will ingest as jsonPayload).
init_structured_logging(
    service=os.getenv("K_SERVICE", "cloudrun_ingestor"),
    env=os.getenv("ENV", "prod"),
    level=os.getenv("LOG_LEVEL", "INFO"),
)

logger = logging.getLogger("cloudrun_ingestor")

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

    log_standard_event(
        logger,
        "cloudrun.process_start",
        severity="INFO",
        outcome="success",
        instance_uptime_ms=_instance_uptime_ms(),
        **_identity_fields(),
    )
except Exception:
    pass


def override_config():
    """Overrides hardcoded config from vm_ingest with environment variables."""
    try:
        import backend.ingestion.config as config_module
        config_module.PROJECT_ID = os.environ["GCP_PROJECT"]
        config_module.SYSTEM_EVENTS_TOPIC = os.environ["SYSTEM_EVENTS_TOPIC"]
        config_module.MARKET_TICKS_TOPIC = os.environ["MARKET_TICKS_TOPIC"]
        config_module.MARKET_BARS_1M_TOPIC = os.environ["MARKET_BARS_1M_TOPIC"]
        config_module.TRADE_SIGNALS_TOPIC = os.environ["TRADE_SIGNALS_TOPIC"]
        config_module.INGEST_FLAG_SECRET_ID = os.environ["INGEST_FLAG_SECRET_ID"]
        log_standard_event(
            logger,
            "config.overridden",
            severity="INFO",
            outcome="success",
            config_overridden=True,
        )
    except KeyError as e:
        log_standard_event(
            logger,
            "config.missing_required_env",
            severity="CRITICAL",
            outcome="failure",
            missing_env=str(e),
        )
        if _running_under_gunicorn():
            raise SystemExit(1)
        return
    except ImportError as e:
        _fail_fast_import(e, context="override_config", failed_import="backend.ingestion.config")

def _assert_required_imports() -> None:
    """
    Validate that backend imports used by the worker resolve at process startup.

    This keeps failures crisp (CRITICAL + exit) rather than leaving a "running"
    HTTP process with a dead worker thread.
    """
    try:
        from backend.ingestion.vm_ingest import IngestionService  # noqa: F401
    except Exception as e:
        _fail_fast_import(e, context="startup", failed_import="backend.ingestion.vm_ingest.IngestionService")
    try:
        from backend.ingestion.config import (  # noqa: F401
            HEARTBEAT_INTERVAL_SECONDS,
            FLAG_CHECK_INTERVAL_SECONDS,
        )
    except Exception as e:
        _fail_fast_import(e, context="startup", failed_import="backend.ingestion.config.(HEARTBEAT_INTERVAL_SECONDS, FLAG_CHECK_INTERVAL_SECONDS)")


def _startup_checks() -> None:
    # In production (gunicorn), do these checks at import time so the container crashes fast.
    # In local/CI import smoke checks, we skip to allow `import cloudrun_ingestor.main`.
    if not _running_under_gunicorn():
        return
    override_config()
    _assert_required_imports()


_startup_checks()


# --- Graceful Shutdown Handling ---
SHUTDOWN_FLAG = threading.Event()

def shutdown_handler(signum: int, frame: Any) -> None:
    """Sets the shutdown flag on receiving SIGTERM or SIGINT."""
    log_standard_event(
        logger,
        "cloudrun.shutdown_signal",
        severity="WARNING",
        outcome="shutdown",
        signal=signal.Signals(signum).name,
    )
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
    log_standard_event(logger, "cloudrun.worker.start", severity="INFO", outcome="started")
    # Wait until shutdown. No work here by design.
    SHUTDOWN_FLAG.wait()
    log_standard_event(logger, "cloudrun.worker.shutdown", severity="WARNING", outcome="shutdown")


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
        log_standard_event(
            logger,
            "cloudrun.http_request",
            severity="INFO",
            outcome="success",
            cold_start=bool(c.cold_start),
            request_ordinal=int(c.request_ordinal),
            instance_uptime_ms=int(c.instance_uptime_ms),
        )

except Exception:
    pass

@app.route("/")
def index():
    # This endpoint is not strictly necessary for the worker but is useful for health checks.
    return "Ingestion service is running.", 200

# Start the background worker thread when the Flask app initializes.
if _running_under_gunicorn():
    worker_thread = threading.Thread(target=ingestion_worker)
    worker_thread.start()
