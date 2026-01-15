from google.cloud import pubsub_v1
import os
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Import necessary components from backend.common.logging
from backend.common.logging import init_structured_logging, log_standard_event
from backend.common.env import get_env

# Shared constants
SERVICE_NAME = os.getenv("SERVICE_NAME", "marketdata-pubsub-publisher")
ENV = os.getenv("ENV", "prod")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

init_structured_logging(service=SERVICE_NAME, env=ENV, level=LOG_LEVEL)
logger = logging.getLogger(__name__)

HEARTBEAT_LOG_INTERVAL_S = float(os.getenv("OPS_HEARTBEAT_LOG_INTERVAL_S", "60"))
# ─────────────────────────────────────────────────────────────
# Pub/Sub Publisher client initialization
# ─────────────────────────────────────────────────────────────
publisher = pubsub_v1.PublisherClient()


def _topic_path() -> str:
    # Runtime config only (not a secret). Resolve at runtime to avoid import-time access.
    project_id = get_env("PUBSUB_PROJECT_ID", required=True)
    topic_id = get_env("PUBSUB_TOPIC_ID", required=True)
    return publisher.topic_path(project_id, topic_id)

def _publish_message(
    message: Dict[str, Any],
    attributes: Optional[Dict[str, str]] = None,
    timeout_s: float = 30.0,
) -> str:
    """Publishes a message to Pub/Sub."""
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    future = publisher.publish(_topic_path(), data, **(attributes or {}))
    return future.result(timeout=max(0.0, float(timeout_s)))

def publish_heartbeat(
    service_name: str,
    git_sha: str | None = None,
    build_id: str | None = None,
    instance_id: str | None = None,
    agent_mode: str | None = None,
    git_ref: str | None = None,
    app_env: str | None = None,
    agent_name: str | None = None,
    agent_role: str | None = None,
    agent_version: str | None = None,
    custom_fields: Dict[str, Any] | None = None,
) -> None:
    """Publishes a heartbeat message."""
    timestamp = datetime.now(timezone.utc).isoformat()
    message: Dict[str, Any] = {
        "event_type": "heartbeat",
        "service_name": service_name,
        "timestamp": timestamp,
        "git_sha": git_sha or os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        "build_id": build_id or os.getenv("BUILD_ID") or None,
        "instance_id": instance_id or os.getenv("INSTANCE_ID") or None,
        "agent_mode": agent_mode or os.getenv("AGENT_MODE") or None,
        "git_ref": git_sha or os.getenv("GIT_SHA") or os.getenv("GITHUB_SHA") or None,
        "app_env": app_env or os.getenv("ENVIRONMENT") or os.getenv("ENV") or None,
        "agent_name": agent_name or os.getenv("AGENT_NAME") or None,
        "agent_role": agent_role or os.getenv("AGENT_ROLE") or None,
        "agent_version": agent_version or os.getenv("AGENT_VERSION") or None,
    }
    if custom_fields:
        message.update(custom_fields)

    try:
        _publish_message(message=message)
    except Exception as e:
        logger.error(
            "Failed to publish heartbeat message",
            extra={
                "event_type": "heartbeat.publish_failed",
                "error": str(e),
                "severity": "ERROR",
            },
        )
