from backend.common.env import get_env
from backend.common.logging import init_structured_logging, log_standard_event
from backend.common.timeutils import normalize_alpaca_timestamp
from backend.common.pubsub_publisher import PubsubPublisher
import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, TypeVar

from google.cloud import firestore
from google.api_core.exceptions import GoogleAPICallError

from backend.common.lifecycle import get_agent_lifecycle_details
from backend.common.agent_mode import read_agent_mode
from backend.common.runtime_fingerprint import get_runtime_fingerprint
from backend.common.agent_mode_guard import AgentModeGuard
from backend.common.kill_switch import KillSwitch
from backend.common.execution_confirm import ExecutionConfirm

SERVICE_NAME = os.getenv("SERVICE_NAME", "ingestion-service")
ENV = os.getenv("ENV", "prod")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

init_structured_logging(service=SERVICE_NAME, env=ENV, level=LOG_LEVEL)
logger = logging.getLogger(__name__)

max_age_s = float(os.getenv("LIVEZ_MAX_AGE_S") or "5")
expected_sub_id = (os.getenv("INGEST_HEARTBEAT_SUBSCRIPTION_ID") or "ingest-heartbeat").strip() or "ingest-heartbeat"
topic_id = (os.getenv("INGEST_HEARTBEAT_TOPIC_ID") or "ingest-heartbeat").strip() or "ingest-heartbeat"

project_id = (
    get_env("FIRESTORE_PROJECT_ID")
    or get_env("FIREBASE_PROJECT_ID")
    or get_env("GCP_PROJECT")
    or get_env("GOOGLE_CLOUD_PROJECT")
)

if not project_id:
    raise RuntimeError("Project ID is required but not found in secrets or environment.")

# Use PubsubPublisher for publishing
pubsub_publisher = PubsubPublisher(project_id=project_id)

subscription_id = expected_sub_id
topic_id = topic_id

# Check required values after fetching secrets
if not subscription_id:
    raise RuntimeError("Subscription ID is required but not found in secrets or environment.")
if not topic_id:
    raise RuntimeError("Topic ID is required but not found in secrets or environment.")

# ... rest of the file ...
