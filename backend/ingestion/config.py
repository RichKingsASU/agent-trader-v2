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

from backend.common.config import env_int, env_str

def _int_env(name: str, default: int) -> int:
    # Back-compat wrapper; prefer backend.common.config.env_int in new code.
    v = env_int(name, default=int(default), required=False)
    return int(v) if v is not None else int(default)


# Core project/topic identifiers (expected to be overridden by env in Cloud Run).
PROJECT_ID: str = (env_str("GCP_PROJECT") or env_str("GOOGLE_CLOUD_PROJECT") or env_str("PUBSUB_PROJECT_ID") or "").strip()
SYSTEM_EVENTS_TOPIC: str = (env_str("SYSTEM_EVENTS_TOPIC") or "").strip()
MARKET_TICKS_TOPIC: str = (env_str("MARKET_TICKS_TOPIC") or "").strip()
MARKET_BARS_1M_TOPIC: str = (env_str("MARKET_BARS_1M_TOPIC") or "").strip()
TRADE_SIGNALS_TOPIC: str = (env_str("TRADE_SIGNALS_TOPIC") or "").strip()
INGEST_FLAG_SECRET_ID: str = (env_str("INGEST_FLAG_SECRET_ID") or "").strip()


# Loop timing defaults (seconds).
# Support both historical *_SECONDS names and newer *_S names used elsewhere.
HEARTBEAT_INTERVAL_SECONDS: int = _int_env("HEARTBEAT_INTERVAL_SECONDS", _int_env("HEARTBEAT_INTERVAL_S", 15))
FLAG_CHECK_INTERVAL_SECONDS: int = _int_env("FLAG_CHECK_INTERVAL_SECONDS", _int_env("FLAG_CHECK_INTERVAL_S", 30))

