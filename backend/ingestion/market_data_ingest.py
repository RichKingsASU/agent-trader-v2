from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from backend.common.secrets import get_secret

@dataclass(frozen=True)
class MarketDataIngestRuntimeConfig:
    service: str
    pipeline_id: str
    git_sha: str | None
    build_id: str | None
    timeout: float
    max_attempts: int
    min_sleep_s: float
    ingest_poll_s: float
    project_id: str
    pubsub_project_id: str
    topic_id: str
    event_type: str
    interval_s: float
    base_px: float
    project_id_for_pubsub: str
    tenant_id: str | None
    global_writes_per_sec: float
    global_burst: float
    flush_interval_ms: int
    heartbeat_interval_s: float


def load_market_data_ingest_runtime_config() -> MarketDataIngestRuntimeConfig:
    """
    Load runtime config from env + secrets (no secret access at import time).
    """
    service = str(
        os.getenv("SERVICE_NAME", "market-data-ingest")
        or os.getenv("K_SERVICE")
        or os.getenv("AGENT_NAME")
        or "market-data-ingest"
    )
    pipeline_id = (os.getenv("INGEST_PIPELINE_ID") or os.getenv("AGENT_NAME") or "market-ingest").strip() or "market-ingest"
    git_sha = (os.getenv("GIT_SHA") or os.getenv("K_REVISION") or "").strip() or None
    build_id = os.getenv("BUILD_ID") or None
    timeout = float(os.getenv("INGEST_HEARTBEAT_PUBLISH_TIMEOUT_S") or "2")
    max_attempts = int(os.getenv("RECONNECT_MAX_ATTEMPTS", "5"))
    min_sleep_s = float(os.getenv("RECONNECT_MIN_SLEEP_S", "0.5"))
    ingest_poll_s = float(os.getenv("INGEST_ENABLED_POLL_S", "5"))

    # Project ID retrieval: prioritize secrets, then fall back to env vars.
    project_id = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
    if not project_id:
        project_id = get_secret("GCP_PROJECT", fail_if_missing=False)
    if not project_id:
        project_id = get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False)
    if not project_id:
        project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""

    # Pub/Sub Project ID retrieval: prioritize secrets, then fall back to env vars.
    pubsub_project_id = get_secret("PUBSUB_PROJECT_ID", fail_if_missing=False)
    if not pubsub_project_id:
        pubsub_project_id = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
    if not pubsub_project_id:
        pubsub_project_id = get_secret("GCP_PROJECT", fail_if_missing=False)
    if not pubsub_project_id:
        pubsub_project_id = get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False)
    if not pubsub_project_id:
        pubsub_project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""

    topic_id = get_secret("MARKET_BARS_1M_TOPIC_ID", fail_if_missing=True)
    event_type = (os.getenv("MARKET_BARS_1M_EVENT_TYPE") or "market.bars.1m").strip()
    interval_s = float(os.getenv("SYNTHETIC_BAR_INTERVAL_S") or "5")
    base_px = float(os.getenv("SYNTHETIC_BASE_PRICE") or "500.0")

    project_id_for_pubsub = get_secret("PUBSUB_PROJECT_ID", fail_if_missing=False)
    if not project_id_for_pubsub:
        project_id_for_pubsub = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
    if not project_id_for_pubsub:
        project_id_for_pubsub = get_secret("GCP_PROJECT", fail_if_missing=False)
    if not project_id_for_pubsub:
        project_id_for_pubsub = get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False)
    if not project_id_for_pubsub:
        project_id_for_pubsub = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""

    if not project_id_for_pubsub:
        raise RuntimeError("Project ID is required but not found in secrets or environment.")

    tenant_id = os.getenv("TENANT_ID") or None
    global_writes_per_sec = float(os.getenv("GLOBAL_WRITES_PER_SEC", "20"))
    global_burst = float(os.getenv("GLOBAL_BURST", "40"))
    flush_interval_ms = int(os.getenv("FLUSH_INTERVAL_MS", "200"))
    heartbeat_interval_s = float(os.getenv("HEARTBEAT_INTERVAL_S", "15"))

    return MarketDataIngestRuntimeConfig(
        service=service,
        pipeline_id=pipeline_id,
        git_sha=git_sha,
        build_id=build_id,
        timeout=timeout,
        max_attempts=max_attempts,
        min_sleep_s=min_sleep_s,
        ingest_poll_s=ingest_poll_s,
        project_id=str(project_id or ""),
        pubsub_project_id=str(pubsub_project_id or ""),
        topic_id=str(topic_id or ""),
        event_type=str(event_type or ""),
        interval_s=float(interval_s),
        base_px=float(base_px),
        project_id_for_pubsub=str(project_id_for_pubsub or ""),
        tenant_id=tenant_id,
        global_writes_per_sec=float(global_writes_per_sec),
        global_burst=float(global_burst),
        flush_interval_ms=int(flush_interval_ms),
        heartbeat_interval_s=float(heartbeat_interval_s),
    )


def ingest_historical_bars(
    *,
    symbols: list[str],
    start: datetime,
    end: datetime,
    db_url: str,
    feed: str = "iex",
    alpaca_api_key_id: str | None = None,
    alpaca_api_secret_key: str | None = None,
    alpaca_data_base_url: str = "https://data.alpaca.markets",
    session: str | None = None,
) -> int:
    """
    Orchestration-only historical 1m bars ingest (REST fetch + DB upsert).

    Note: the underlying REST/DB primitives live in `backend.ingestion.alpaca_rest_backfill`
    and intentionally do not import alpaca-py or Pub/Sub.
    """
    # Import inside the function so this module remains orchestration-only and
    # doesn't pull in HTTP/DB libs unless this path is executed.
    from backend.ingestion.alpaca_rest_backfill import (  # noqa: WPS433
        AlpacaRestAuth,
        fetch_alpaca_bars_1m,
        upsert_market_data_1m_bars,
    )

    key_id = (alpaca_api_key_id or os.getenv("APCA_API_KEY_ID") or "").strip()
    secret = (alpaca_api_secret_key or os.getenv("APCA_API_SECRET_KEY") or "").strip()
    if not key_id or not secret:
        raise RuntimeError("Missing Alpaca credentials (APCA_API_KEY_ID/APCA_API_SECRET_KEY)")

    auth = AlpacaRestAuth(api_key_id=key_id, api_secret_key=secret)

    total = 0
    for sym in symbols:
        bars = fetch_alpaca_bars_1m(
            symbol=str(sym),
            start=start,
            end=end,
            auth=auth,
            feed=feed,
            base_url=alpaca_data_base_url,
        )
        total += upsert_market_data_1m_bars(db_url=db_url, bars=bars, session=session)

    return total
