from backend.common.secrets import get_secret
import os

service = str(os.getenv("SERVICE_NAME", "market-data-ingest") or os.getenv("K_SERVICE") or os.getenv("AGENT_NAME") or "market-data-ingest")
pipeline_id = (os.getenv("INGEST_PIPELINE_ID") or os.getenv("AGENT_NAME") or "market-ingest").strip() or "market-ingest"
git_sha = (os.getenv("GIT_SHA") or os.getenv("K_REVISION") or "").strip() or None
build_id = os.getenv("BUILD_ID") or None
timeout=float(os.getenv("INGEST_HEARTBEAT_PUBLISH_TIMEOUT_S") or "2")
max_attempts = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "5"))
min_sleep_s = float(os.getenv("RECONNECT_MIN_SLEEP_S", "0.5"))
ingest_poll_s = float(os.getenv("INGEST_ENABLED_POLL_S", "5"))

# Project ID retrieval: prioritize secrets, then fall back to env vars.
project_id = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
if not project_id:
    project_id = get_secret("GCP_PROJECT", fail_if_missing=False)
if not project_id:
    project_id = get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False)

# If project ID is still missing after checking secrets, use environment variables as a last resort config.
if not project_id:
    project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""

# Pub/Sub Project ID retrieval: prioritize secrets, then fall back to env vars.
# This is slightly different from above as it has a specific fallback for PUBSUB_PROJECT_ID if available.
pubsub_project_id = get_secret("PUBSUB_PROJECT_ID", fail_if_missing=False)
if not pubsub_project_id:
    # Fallback using common project ID sources if PUBSUB_PROJECT_ID secret is missing.
    pubsub_project_id = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False) # Fallback if PUBSUB_PROJECT_ID secret is missing
if not pubsub_project_id:
    pubsub_project_id = get_secret("GCP_PROJECT", fail_if_missing=False) # Fallback to GCP_PROJECT secret
if not pubsub_project_id:
    pubsub_project_id = get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False) # Fallback to GOOGLE_CLOUD_PROJECT secret

# If project ID is still missing after checking secrets, use env var as last resort config.
if not pubsub_project_id:
    pubsub_project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""

topic_id = get_secret("MARKET_BARS_1M_TOPIC_ID", fail_if_missing=True)
event_type = (os.getenv("MARKET_BARS_1M_EVENT_TYPE") or "market.bars.1m").strip()
interval_s = float(os.getenv("SYNTHETIC_BAR_INTERVAL_S") or "5")
base_px = float(os.getenv("SYNTHETIC_BASE_PRICE") or "500.0")

# Pub/Sub Project ID retrieval
# Check secrets first, then fall back to env vars.
# NOTE: In a strict interpretation, even project IDs should be secrets.
# However, get_firebase_project_id in env.py already handles this with get_secret fallbacks.
# For consistency and clarity, explicitly use get_secret here.
project_id_for_pubsub = get_secret("PUBSUB_PROJECT_ID", fail_if_missing=False)
if not project_id_for_pubsub:
    # Fallback using common project ID sources if PUBSUB_PROJECT_ID secret is missing.
    project_id_for_pubsub = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False) # Fallback if PUBSUB_PROJECT_ID secret is missing
if not project_id_for_pubsub:
    project_id_for_pubsub = get_secret("GCP_PROJECT", fail_if_missing=False) # Fallback to GCP_PROJECT secret
if not project_id_for_pubsub:
    project_id_for_pubsub = get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False) # Fallback to GOOGLE_CLOUD_PROJECT secret

# If project ID is still missing after checking secrets, use env var as last resort config.
if not project_id_for_pubsub:
    project_id_for_pubsub = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""

if not project_id_for_pubsub:
    # Project ID is required for Pub/Sub operations.
    raise RuntimeError("Project ID is required but not found in secrets or environment.")

tenant_id = os.getenv("TENANT_ID") or None
global_writes_per_sec = float(os.getenv("GLOBAL_WRITES_PER_SEC", "20"))
global_burst = float(os.getenv("GLOBAL_BURST", "40"))
flush_interval_ms = int(os.getenv("FLUSH_INTERVAL_MS", "200"))
heartbeat_interval_s = float(os.getenv("HEARTBEAT_INTERVAL_S", "15"))
