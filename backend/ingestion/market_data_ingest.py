from backend.common.env import get_env
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
import os

service = str(os.getenv("SERVICE_NAME", "market-data-ingest") or os.getenv("K_SERVICE") or os.getenv("AGENT_NAME") or "market-data-ingest")
pipeline_id = (os.getenv("INGEST_PIPELINE_ID") or os.getenv("AGENT_NAME") or "market-ingest").strip() or "market-ingest"
git_sha = (os.getenv("GIT_SHA") or os.getenv("K_REVISION") or "").strip() or None
build_id = os.getenv("BUILD_ID") or None
timeout=float(os.getenv("INGEST_HEARTBEAT_PUBLISH_TIMEOUT_S") or "2")
max_attempts = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "5"))
min_sleep_s = float(os.getenv("RECONNECT_MIN_SLEEP_S", "0.5"))
ingest_poll_s = float(os.getenv("INGEST_ENABLED_POLL_S", "5"))

# Project id is runtime configuration (not a secret).
project_id = (
    get_env("FIRESTORE_PROJECT_ID")
    or get_env("FIREBASE_PROJECT_ID")
    or get_env("GCP_PROJECT")
    or get_env("GOOGLE_CLOUD_PROJECT")
)

# Pub/Sub project id is runtime configuration (not a secret).
pubsub_project_id = (
    get_env("PUBSUB_PROJECT_ID")
    or get_env("GCP_PROJECT")
    or get_env("GOOGLE_CLOUD_PROJECT")
)

topic_id = get_env("MARKET_BARS_1M_TOPIC_ID", required=True)
event_type = (os.getenv("MARKET_BARS_1M_EVENT_TYPE") or "market.bars.1m").strip()
interval_s = float(os.getenv("SYNTHETIC_BAR_INTERVAL_S") or "5")
base_px = float(os.getenv("SYNTHETIC_BASE_PRICE") or "500.0")

project_id_for_pubsub = pubsub_project_id

if not project_id_for_pubsub:
    # Project ID is required for Pub/Sub operations.
    raise RuntimeError("Project ID is required but not found in secrets or environment.")

tenant_id = os.getenv("TENANT_ID") or None
global_writes_per_sec = float(os.getenv("GLOBAL_WRITES_PER_SEC", "20"))
global_burst = float(os.getenv("GLOBAL_BURST", "40"))
flush_interval_ms = int(os.getenv("FLUSH_INTERVAL_MS", "200"))
heartbeat_interval_s = float(os.getenv("HEARTBEAT_INTERVAL_S", "15"))
