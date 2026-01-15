from backend.common.secrets import get_secret
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

# Project ID retrieval: prioritize secrets, then fall back to env vars.
project_id = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
if not project_id:
    project_id = get_secret("GCP_PROJECT", fail_if_missing=False)
if not project_id:
    project_id = get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False)

# If project ID is still missing after checking secrets, use environment variables as a last resort config.
if not project_id:
    project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""

if not project_id:
    raise RuntimeError("Project ID is required but not found in secrets or environment.")

# Use PubsubPublisher for publishing
pubsub_publisher = PubsubPublisher(project_id=project_id)

# Sub ID retrieval: prioritize secret, then env var, then default.
subscription_id = get_secret("INGEST_HEARTBEAT_SUBSCRIPTION_ID", fail_if_missing=True) or expected_sub_id
subscription_id = str(subscription_id).strip() or expected_sub_id

# Topic ID retrieval: prioritize secret, then env var, then default.
topic_id_secret = get_secret("INGEST_HEARTBEAT_TOPIC_ID", fail_if_missing=True) or topic_id
topic_id = str(topic_id_secret).strip() or topic_id

# Check required values after fetching secrets
if not subscription_id:
    raise RuntimeError("Subscription ID is required but not found in secrets or environment.")
if not topic_id:
    raise RuntimeError("Topic ID is required but not found in secrets or environment.")

# ... rest of the file ...
