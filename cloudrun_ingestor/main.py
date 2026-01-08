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
import time
import uuid
from typing import Any

# --- Structured Logging & Pre-run Configuration ---
# This must run before any other modules are imported to ensure logging is configured correctly.

# Set up structured logging with the google-cloud-logging library.
# In CI/local environments, Application Default Credentials may be unavailable; in that case,
# fall back to standard logging rather than crashing at import-time.
try:
    import google.cloud.logging  # type: ignore

    logging_client = google.cloud.logging.Client()
    logging_client.setup_logging()
except Exception as e:  # noqa: BLE001 - best-effort logging initialization
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
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

# Provide a minimal fallback handler early so CRITICAL logs are visible even if
# structured logging dependencies are missing/misconfigured.
logging.basicConfig(level=logging.INFO)

# Log Python import/resolve context as early as possible (before structured logging setup),
# so failures in logging initialization still have `sys.path` visibility.
logger.info(
    "Python startup diagnostics (pre-logging setup). sys.path=%s",
    list(sys.path),
    extra={
        **LOG_EXTRA,
        "event_type": "python.startup",
        "python_executable": sys.executable,
        "python_version": sys.version,
        "cwd": os.getcwd(),
        "pythonpath_env": os.getenv("PYTHONPATH") or "",
        "sys_path": list(sys.path),
        "pythonpath_assumption": "Repo root (containing `backend/`) must be on sys.path (often via PYTHONPATH).",
    },
)

# Set up structured logging with the google-cloud-logging library.
# This will automatically format logs as JSON and include standard Cloud Run fields.
try:
    import google.cloud.logging

    logging_client = google.cloud.logging.Client()
    logging_client.setup_logging()
except Exception as e:
    logger.critical(
        "Failed to initialize structured logging (google-cloud-logging): %s",
        e,
        extra={
            **LOG_EXTRA,
            "event_type": "python.logging_setup_failed",
            "errorType": e.__class__.__name__,
            "error": str(e),
            "cwd": os.getcwd(),
            "pythonpath_env": os.getenv("PYTHONPATH") or "",
            "sys_path": list(sys.path),
        },
        exc_info=True,
    )
    sys.exit(1)

def _fail_fast_import(error: BaseException, *, context: str, failed_import: str) -> None:
    logger.critical(
        "Import failure (%s): %s",
        failed_import,
        error,
        extra={
            **LOG_EXTRA,
            "event_type": "python.import_failed",
            "context": context,
            "failed_import": failed_import,
            "errorType": error.__class__.__name__,
            "error": str(error),
            "cwd": os.getcwd(),
            "pythonpath_env": os.getenv("PYTHONPATH") or "",
            "sys_path": list(sys.path),
        },
        exc_info=True,
    )
    sys.exit(1)


def override_config():
    """Overrides hardcoded config from vm_ingest with environment variables."""
    try:
        import backend.ingestion.config as config_module
        logger.info(
            "Imported backend.ingestion.config successfully.",
            extra={**LOG_EXTRA, "module": "backend.ingestion.config", "module_file": getattr(config_module, "__file__", None)},
        )
        config_module.PROJECT_ID = os.environ["GCP_PROJECT_ID"]
        config_module.SYSTEM_EVENTS_TOPIC = os.environ["SYSTEM_EVENTS_TOPIC"]
        config_module.MARKET_TICKS_TOPIC = os.environ["MARKET_TICKS_TOPIC"]
        config_module.MARKET_BARS_1M_TOPIC = os.environ["MARKET_BARS_1M_TOPIC"]
        config_module.TRADE_SIGNALS_TOPIC = os.environ["TRADE_SIGNALS_TOPIC"]
        config_module.INGEST_FLAG_SECRET_ID = os.environ["INGEST_FLAG_SECRET_ID"]
        logger.info("Configuration overridden for project: %s", config_module.PROJECT_ID, extra=LOG_EXTRA)
    except KeyError as e:
        logger.critical("Missing required environment variable: %s", e, extra=LOG_EXTRA)
        sys.exit(1)
    except ImportError as e:
        _fail_fast_import(e, context="override_config", failed_import="backend.ingestion.config")

override_config()

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


_assert_required_imports()


# --- Graceful Shutdown Handling ---
SHUTDOWN_FLAG = threading.Event()

def shutdown_handler(signum: int, frame: Any):
    """Sets the shutdown flag on receiving SIGTERM or SIGINT."""
    log_data = {**LOG_EXTRA, "signal": signal.Signals(signum).name}
    logger.warning("Shutdown signal received. Exiting main loop.", extra=log_data)
    SHUTDOWN_FLAG.set()


# Register the shutdown handler
signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)


# --- Background Worker for Ingestion Loop ---
def ingestion_worker():
    """The main application logic, designed to be run in a background thread."""
    try:
        from backend.ingestion.vm_ingest import IngestionService
        from backend.ingestion.config import (
            HEARTBEAT_INTERVAL_SECONDS,
            FLAG_CHECK_INTERVAL_SECONDS,
        )
    except ImportError as e:
        # This is unrecoverable: fail fast so Cloud Run restarts with a clear signal.
        logger.critical(
            "Failed to import ingestion dependencies: %s",
            e,
            extra={
                **LOG_EXTRA,
                "event_type": "python.import_failed",
                "context": "ingestion_worker",
                "cwd": os.getcwd(),
                "pythonpath_env": os.getenv("PYTHONPATH") or "",
                "sys_path": list(sys.path),
            },
            exc_info=True,
        )
        os._exit(1)

    logger.info("Ingestion worker thread started.", extra=LOG_EXTRA)
    service = IngestionService()
    service.health_checker.sanity_checks()

    # Supervisor loop: the worker must not exit unless shutdown is requested.
    while not SHUTDOWN_FLAG.is_set():
        try:
            from backend.ingestion.vm_ingest import IngestionService
            import backend.ingestion.config as config_module
            from backend.ingestion.config import (
                HEARTBEAT_INTERVAL_SECONDS,
                FLAG_CHECK_INTERVAL_SECONDS,
            )

            logger.info(
                "Imported ingestion modules successfully.",
                extra={
                    **LOG_EXTRA,
                    "module": "backend.ingestion.config",
                    "module_file": getattr(config_module, "__file__", None),
                },
            )

            service = IngestionService()
            service.health_checker.sanity_checks()
            logger.info("Ingestion worker initialized.", extra=LOG_EXTRA)
        except Exception:
            # Log full stack trace; keep process alive and retry until shutdown.
            retry_seconds = 5
            logger.exception(
                "Failed to initialize ingestion worker; retrying.",
                extra={**LOG_EXTRA, "retry_in_seconds": retry_seconds},
            )
            SHUTDOWN_FLAG.wait(timeout=retry_seconds)
            continue

        while not SHUTDOWN_FLAG.is_set():
            iteration_id = uuid.uuid4().hex
            loop_log_extra = {**LOG_EXTRA, "iteration_id": iteration_id}

            try:
                # Check for kill switch
                if time.time() - service.last_flag_check > FLAG_CHECK_INTERVAL_SECONDS:
                    service.ingest_enabled = service.health_checker.check_ingest_flag()
                    service.last_flag_check = time.time()

                if not service.ingest_enabled:
                    logger.warning("Ingestion is disabled via feature flag. Sleeping.", extra=loop_log_extra)
                    time.sleep(HEARTBEAT_INTERVAL_SECONDS)
                    continue

                # Publish events (business logic is unchanged)
                service.publish_system_event("info", "Ingestion heartbeat.")
                logger.info(
                    "Published system heartbeat.",
                    extra={**loop_log_extra, "published_topic": service.system_events_topic_path},
                )

                service.publish_market_tick()
                logger.info(
                    "Published market tick.",
                    extra={**loop_log_extra, "published_topic": service.market_ticks_topic_path},
                )

                service.publish_market_bar_1m()
                logger.info(
                    "Published market bar.",
                    extra={**loop_log_extra, "published_topic": service.market_bars_1m_topic_path},
                )

                service.publish_trade_signal()
                logger.info(
                    "Published trade signal.",
                    extra={**loop_log_extra, "published_topic": service.trade_signals_topic_path},
                )

            except Exception:
                # Log full stack trace; keep the loop alive.
                logger.exception("Error in ingestion loop.", extra=loop_log_extra)

            # Wait for the next iteration or shutdown signal
            SHUTDOWN_FLAG.wait(timeout=HEARTBEAT_INTERVAL_SECONDS)

        if not SHUTDOWN_FLAG.is_set():
            # Defensive: the publish loop should only exit on shutdown.
            logger.error("Ingestion loop exited without shutdown; restarting.", extra=LOG_EXTRA)

    logger.warning("Ingestion worker shutting down.", extra=LOG_EXTRA)


# --- Flask App for Gunicorn ---
# A minimal Flask app is required for Gunicorn to have a process to manage.
# The actual work is done in the background thread.
try:
    from flask import Flask
except Exception as e:
    _fail_fast_import(e, context="startup", failed_import="flask.Flask")
app = Flask(__name__)

@app.route("/")
def index():
    # This endpoint is not strictly necessary for the worker but is useful for health checks.
    return "Ingestion service is running.", 200

# Start the background worker thread when the Flask app initializes.
worker_thread = threading.Thread(target=ingestion_worker)
worker_thread.start()
