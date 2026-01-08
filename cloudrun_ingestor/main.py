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

# Set up structured logging with the google-cloud-logging library
# This will automatically format logs as JSON and include standard Cloud Run fields.
import google.cloud.logging
logging_client = google.cloud.logging.Client()
logging_client.setup_logging()

# Set up a logger adapter to inject custom static fields into all log messages.
LOG_EXTRA = {
    "service": os.getenv("K_SERVICE", "cloudrun_ingestor"),
    "env": os.getenv("ENV", "prod"),
}
logger = logging.getLogger(__name__)

try:
    from backend.common.cloudrun_perf import identity_fields as _identity_fields  # noqa: WPS433
    from backend.common.cloudrun_perf import instance_uptime_ms as _instance_uptime_ms  # noqa: WPS433

    logger.info(
        "Cloud Run process start",
        extra={**LOG_EXTRA, "event_type": "cloudrun.process_start", "instance_uptime_ms": _instance_uptime_ms(), **_identity_fields()},
    )
except Exception:
    pass


def override_config():
    """Overrides hardcoded config from vm_ingest with environment variables."""
    try:
        import backend.ingestion.config as config_module
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
    except ImportError:
        logger.critical("Could not import backend.ingestion.config.", extra=LOG_EXTRA)
        sys.exit(1)

override_config()


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
        logger.critical("Failed to import ingestion service: %s", e, extra=LOG_EXTRA)
        return

    logger.info("Ingestion worker thread started.", extra=LOG_EXTRA)
    service = IngestionService()
    service.health_checker.sanity_checks()

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
            logger.info("Published system heartbeat.", extra={**loop_log_extra, "published_topic": service.system_events_topic_path})
            
            service.publish_market_tick()
            logger.info("Published market tick.", extra={**loop_log_extra, "published_topic": service.market_ticks_topic_path})

            service.publish_market_bar_1m()
            logger.info("Published market bar.", extra={**loop_log_extra, "published_topic": service.market_bars_1m_topic_path})

            service.publish_trade_signal()
            logger.info("Published trade signal.", extra={**loop_log_extra, "published_topic": service.trade_signals_topic_path})

        except Exception as e:
            logger.error("Error in ingestion loop: %s", e, extra=loop_log_extra, exc_info=True)

        # Wait for the next iteration or shutdown signal
        SHUTDOWN_FLAG.wait(timeout=HEARTBEAT_INTERVAL_SECONDS)

    logger.warning("Ingestion worker shutting down.", extra=LOG_EXTRA)


# --- Flask App for Gunicorn ---
# A minimal Flask app is required for Gunicorn to have a process to manage.
# The actual work is done in the background thread.
from flask import Flask
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
worker_thread = threading.Thread(target=ingestion_worker)
worker_thread.start()
