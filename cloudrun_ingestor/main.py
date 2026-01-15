from backend.common.env import get_env
import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, TypeVar

from google.cloud import pubsub_v1
from google.api_core.exceptions import GoogleAPICallError

from backend.common.logging import init_structured_logging, log_standard_event
from backend.observability.correlation import bind_correlation_id, get_or_create_correlation_id

from cloudrun_ingestor.event_utils import infer_topic
from cloudrun_ingestor.schema_router import route_payload
from cloudrun_ingestor.config import Config
from cloudrun_ingestor.gunicorn_conf import GunicornConf

SERVICE_NAME = os.getenv("SERVICE_NAME", "cloudrun_ingestor")
ENV = os.getenv("ENV", "prod")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

init_structured_logging(service=SERVICE_NAME, env=ENV, level=LOG_LEVEL)
logger = logging.getLogger(__name__)

_config_module: Config | None = None


def get_config_module() -> Config:
    """
    Resolve Cloud Run ingestor runtime configuration at runtime (never at import time).
    """

    global _config_module
    if _config_module is not None:
        return _config_module

    cfg = Config(
        gcp_project_id=get_env("GCP_PROJECT", required=True),
        system_events_topic_id=get_env("SYSTEM_EVENTS_TOPIC", required=True),
        market_ticks_topic_id=get_env("MARKET_TICKS_TOPIC", required=True),
        market_bars_1m_topic_id=get_env("MARKET_BARS_1M_TOPIC", required=True),
        trade_signals_topic_id=get_env("TRADE_SIGNALS_TOPIC", required=True),
        ingest_flag_secret_id=get_env("INGEST_FLAG_SECRET_ID", required=True),
    )

    # Enforcement logic for INGEST_FLAG_SECRET_ID: hard fail unless explicitly enabled.
    if str(cfg.ingest_flag_secret_id).strip().lower() != "enabled":
        raise RuntimeError(
            f"Ingestion is disabled: INGEST_FLAG_SECRET_ID is set to {cfg.ingest_flag_secret_id!r}, requires 'enabled'."
        )

    _config_module = cfg
    return cfg

# These environment variables are used only for runtime configuration and not secrets.
# They are not fetched from Secret Manager.
if (os.getenv("GUNICORN_CMD_ARGS") or "").strip():
    gunicorn_conf = GunicornConf()
    gunicorn_conf.update_from_env()

def _parse_env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return bool(raw) == True if raw in {"1", "true", "t", "yes", "y", "on"} else default

def _require_env_string(name: str, default: Optional[str] = None) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        if default is not None:
            return default
        raise RuntimeError(f"Missing required env var: {name}")
    return v

def _process_item_once_sync(item: _WorkItem) -> dict[str, Any]:
    """
    Executes the actual materialization work (runs in a worker thread).
    """
    writer: FirestoreWriter = app.state.firestore_writer

    # Visibility-only: detect duplicate deliveries (never gate processing).
    try:
        is_dup = writer.observe_pubsub_delivery(
            message_id=item.message_id,
            topic=item.source_topic,
            subscription=item.subscription,
            handler=item.handler_name,
            published_at=item.publish_time,
            delivery_attempt=item.delivery_attempt,
        )
        if is_dup is True:
            log(
                "pubsub.duplicate_delivery_detected",
                severity="WARNING",
                handler=item.handler_name,
                messageId=item.message_id,
                topic=item.source_topic,
                subscription=item.subscription,
                deliveryAttempt=item.delivery_attempt,
                publishTime=item.publish_time.isoformat(),
            )
    except Exception:
        # Never fail the message due to visibility-only writes.
        pass

    handler_fn = item.handler_fn
    return handler_fn(
        payload=item.payload,
        env=item.env,
        default_region=item.default_region,
        source_topic=item.source_topic,
        message_id=item.message_id,
        pubsub_published_at=item.publish_time,
        firestore_writer=writer,
        replay=item.replay,
    )