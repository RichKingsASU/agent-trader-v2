"""
Compatibility config module for `cloudrun_ingestor`.

The Cloud Run ingestor historically referenced an `ingestion.config` module.
This repo's canonical import pattern requires `from backend....` imports, so we
provide `backend.ingestion.config` as a stable, importable home for those values.

Business logic is intentionally not implemented here; this module only defines
configuration constants that may be overridden by environment at runtime.
"""

from __future__ import annotations

import os


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


# Core project/topic identifiers (expected to be overridden by env in Cloud Run).
PROJECT_ID: str = (os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("PUBSUB_PROJECT_ID") or "").strip()
SYSTEM_EVENTS_TOPIC: str = (os.getenv("SYSTEM_EVENTS_TOPIC") or "").strip()
MARKET_TICKS_TOPIC: str = (os.getenv("MARKET_TICKS_TOPIC") or "").strip()
MARKET_BARS_1M_TOPIC: str = (os.getenv("MARKET_BARS_1M_TOPIC") or "").strip()
TRADE_SIGNALS_TOPIC: str = (os.getenv("TRADE_SIGNALS_TOPIC") or "").strip()
INGEST_FLAG_SECRET_ID: str = (os.getenv("INGEST_FLAG_SECRET_ID") or "").strip()


# Loop timing defaults (seconds).
# Support both historical *_SECONDS names and newer *_S names used elsewhere.
HEARTBEAT_INTERVAL_SECONDS: int = _int_env("HEARTBEAT_INTERVAL_SECONDS", _int_env("HEARTBEAT_INTERVAL_S", 15))
FLAG_CHECK_INTERVAL_SECONDS: int = _int_env("FLAG_CHECK_INTERVAL_SECONDS", _int_env("FLAG_CHECK_INTERVAL_S", 30))

