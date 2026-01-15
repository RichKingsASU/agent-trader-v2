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

SERVICE_NAME = os.getenv("SERVICE_NAME", "event-store")
ENV = os.getenv("ENV", "prod")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

init_structured_logging(service=SERVICE_NAME, env=ENV, level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# Secrets and configuration
mode = (os.getenv("EVENT_STORE") or "").strip().lower()
project_id = get_secret("FIREBASE_PROJECT_ID", fail_if_missing=False) or get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False)
if not project_id:
    # Fallback to non-secret env vars if secrets are not found.
    project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None

if not project_id:
    raise RuntimeError("Project ID is required but not found in secrets or environment.")

# Initialize Firestore client using the determined project_id.
# If emulator is set, use it.
emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")
db_client: firestore.Client | None = None
if emulator_host:
    db_client = firestore.Client(project=project_id, database=str(os.getenv("FIRESTORE_DATABASE") or "(default)"), client_options={"api_endpoint": emulator_host})
else:
    db_client = firestore.Client(project=project_id, database=str(os.getenv("FIRESTORE_DATABASE") or "(default)"))

if db_client is None:
    raise RuntimeError("Firestore client could not be initialized.")

db = db_client