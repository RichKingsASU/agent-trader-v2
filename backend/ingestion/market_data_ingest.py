"""
Market data ingestion utilities.

This module must be importable with **no Pub/Sub side effects**, especially for
historical backfill workflows.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Sequence

import psycopg

from backend.common.secrets import get_secret
from backend.common.timeutils import parse_alpaca_timestamp
from backend.streams.alpaca_env import load_alpaca_env

logger = logging.getLogger(__name__)

DATABASE_URL_SECRET = "DATABASE_URL"

# Lightweight, side-effect-free identity fields (env-only).
service = str(
    os.getenv("SERVICE_NAME", "market-data-ingest")
    or os.getenv("K_SERVICE")
    or os.getenv("AGENT_NAME")
    or "market-data-ingest"
)
pipeline_id = (os.getenv("INGEST_PIPELINE_ID") or os.getenv("AGENT_NAME") or "market-ingest").strip() or "market-ingest"
git_sha = (os.getenv("GIT_SHA") or os.getenv("K_REVISION") or "").strip() or None
build_id = os.getenv("BUILD_ID") or None


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")


def _is_backfill_mode() -> bool:
    # Backfill callers should set this, but we also allow it to default false.
    return _env_bool("IS_BACKFILL", default=False)


def _resolve_symbols(symbols: str | Sequence[str]) -> list[str]:
    if isinstance(symbols, str):
        parts = [s.strip().upper() for s in symbols.split(",")]
        return [s for s in parts if s]
    return [str(s).strip().upper() for s in symbols if str(s).strip()]


def ingest_historical_bars(
    *,
    symbols: str | Sequence[str],
    start: Any,
    end: Any,
    feed: str | None = None,
    chunk_minutes: int | None = None,
    db_batch_size: int | None = None,
) -> int:
    """
    Backfill 1-minute historical bars via Alpaca REST and write directly to Postgres.

    Requirements:
    - Uses Alpaca REST (alpaca-py historical data client), not WebSocket
    - Writes to `public.market_data_1m`
    - Reads Postgres URL via `get_secret(DATABASE_URL_SECRET, ...)`
    - Uses `parse_alpaca_timestamp` for time normalization
    - Does not import/reference Pub/Sub and does not read Pub/Sub secrets
    """

    from alpaca.data.historical import StockHistoricalDataClient  # noqa: WPS433 (local import by design)
    from alpaca.data.requests import StockBarsRequest  # noqa: WPS433 (local import by design)
    from alpaca.data.timeframe import TimeFrame  # noqa: WPS433 (local import by design)

    syms = _resolve_symbols(symbols)
    if not syms:
        raise ValueError("symbols resolved to empty list")

    start_dt = parse_alpaca_timestamp(start).astimezone(timezone.utc)
    end_dt = parse_alpaca_timestamp(end).astimezone(timezone.utc)
    if end_dt <= start_dt:
        raise ValueError(f"end must be after start (start={start_dt.isoformat()} end={end_dt.isoformat()})")

    alpaca = load_alpaca_env(require_keys=True)

    # Default feed comes from env (no secret reads here).
    resolved_feed = (feed or os.getenv("ALPACA_DATA_FEED") or os.getenv("ALPACA_FEED") or "iex").strip().lower() or "iex"

    # Alpaca limit is 10k bars per request; use a conservative chunk to avoid overshooting
    # when extended hours are included.
    chunk_m = int(chunk_minutes or int(os.getenv("ALPACA_BACKFILL_CHUNK_MINUTES") or 7200))  # 5 days
    batch_sz = int(db_batch_size or int(os.getenv("DB_INSERT_BATCH_SIZE") or 2000))

    db_url = get_secret(DATABASE_URL_SECRET, fail_if_missing=True)
    if not db_url:
        raise RuntimeError("DATABASE_URL secret resolved to empty value")

    client = StockHistoricalDataClient(
        api_key=alpaca.key_id,
        secret_key=alpaca.secret_key,
        url_override=alpaca.data_host,
    )

    insert_sql = """
    INSERT INTO public.market_data_1m (
        symbol, ts, open, high, low, close, volume
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """

    total_rows_attempted = 0
    cur_start = start_dt

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            while cur_start < end_dt:
                cur_end = min(end_dt, cur_start + timedelta(minutes=chunk_m))

                req = StockBarsRequest(
                    symbol_or_symbols=syms,
                    timeframe=TimeFrame.Minute,
                    start=cur_start,
                    end=cur_end,
                    feed=resolved_feed,
                )

                barset = client.get_stock_bars(req)

                rows: list[tuple[str, datetime, float, float, float, float, int]] = []
                data = getattr(barset, "data", None) or {}
                for sym, bars in data.items():
                    for b in (bars or []):
                        ts = parse_alpaca_timestamp(getattr(b, "timestamp", None)).astimezone(timezone.utc)
                        rows.append(
                            (
                                str(sym).upper(),
                                ts,
                                float(getattr(b, "open")),
                                float(getattr(b, "high")),
                                float(getattr(b, "low")),
                                float(getattr(b, "close")),
                                int(getattr(b, "volume") or 0),
                            )
                        )

                if rows:
                    # Batch inserts for performance.
                    for i in range(0, len(rows), batch_sz):
                        batch = rows[i : i + batch_sz]
                        cur.executemany(insert_sql, batch)
                    conn.commit()
                    total_rows_attempted += len(rows)
                    logger.info(
                        "historical_bars_chunk_written",
                        extra={
                            "event_type": "market_data.backfill.written",
                            "symbols": syms,
                            "feed": resolved_feed,
                            "chunk_start": cur_start.isoformat(),
                            "chunk_end": cur_end.isoformat(),
                            "rows_attempted": len(rows),
                        },
                    )
                else:
                    logger.info(
                        "historical_bars_chunk_empty",
                        extra={
                            "event_type": "market_data.backfill.empty",
                            "symbols": syms,
                            "feed": resolved_feed,
                            "chunk_start": cur_start.isoformat(),
                            "chunk_end": cur_end.isoformat(),
                        },
                    )

                cur_start = cur_end

    return total_rows_attempted


def _init_pubsub_publisher_if_enabled() -> tuple[Any, str] | None:
    """
    Initialize Pub/Sub publisher lazily.

    IMPORTANT:
    - Must only be called inside runtime (never at import time)
    - Must not run during backfill (IS_BACKFILL)
    """

    if _is_backfill_mode():
        return None

    # Local imports so importing this module doesn't pull in Pub/Sub dependencies or secrets.
    from google.cloud import pubsub_v1  # noqa: WPS433 (local import by design)

    topic_id = get_secret("MARKET_BARS_1M_TOPIC_ID", fail_if_missing=True)
    project_id = (
        get_secret("PUBSUB_PROJECT_ID", fail_if_missing=False)
        or get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
        or get_secret("GCP_PROJECT", fail_if_missing=False)
        or get_secret("GOOGLE_CLOUD_PROJECT", fail_if_missing=False)
        or os.getenv("GCP_PROJECT")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()
    if not project_id:
        raise RuntimeError("PUBSUB project_id is required but was not found")

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, str(topic_id).strip())
    return publisher, topic_path


__all__ = [
    "DATABASE_URL_SECRET",
    "ingest_historical_bars",
]
