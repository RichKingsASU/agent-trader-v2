from backend.common.secrets import get_secret
from google.cloud import pubsub_v1
import os
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Import necessary components from backend.common.logging
from backend.common.logging import init_structured_logging, log_standard_event

# Shared constants
SERVICE_NAME = os.getenv("SERVICE_NAME", "strategy-engine-heartbeat-subscriber")
ENV = os.getenv("ENV", "prod")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

init_structured_logging(service=SERVICE_NAME, env=ENV, level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# Load configuration from environment variables, prioritizing Secret Manager
PROJECT_ID = get_secret("PUBSUB_PROJECT_ID", fail_if_missing=True)
SUBSCRIPTION_ID = get_secret("PUBSUB_SUBSCRIPTION_ID", fail_if_missing=True)

HEARTBEAT_LOG_INTERVAL_S = float(os.getenv("OPS_HEARTBEAT_LOG_INTERVAL_S", "60"))
# ─────────────────────────────────────────────────────────────
# Pub/Sub Subscriber client initialization
# ─────────────────────────────────────────────────────────────
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

def _process_message(message: Any, data: bytes) -> None:
    """Processes a single Pub/Sub message."""
    try:
        # Log the heartbeat message with relevant metadata
        logger.info(
            "Received heartbeat message",
            extra={
                "event_type": "heartbeat.received",
                "message_id": message.get("messageId"),
                "publish_time": message.get("publishTime"),
                "attributes": message.get("attributes"),
                "data": data.decode("utf-8"),
            },
        )
    except Exception as e:
        logger.error(
            f"Failed to process heartbeat message: {e}",
            extra={
                "event_type": "heartbeat.process_failed",
                "error": str(e),
                "severity": "ERROR",
            },
        )

async def subscribe_heartbeats() -> None:
    """Subscribes to the Pub/Sub topic and processes heartbeat messages."""
    logger.info(f"Subscribing to subscription: {subscription_path}")
    try:
        streaming_pull_response = subscriber.subscribe(subscription_path, callback=_process_message)
        # Keep the subscriber running indefinitely
        await streaming_pull_response
    except Exception as e:
        logger.critical(
            f"Failed to subscribe to Pub/Sub topic: {e}",
            extra={"event_type": "pubsub.subscribe_failed", "error": str(e)},
        )
        raise

