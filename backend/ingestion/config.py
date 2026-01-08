"""
Canonical ingestion configuration module.

This module must be safe to import in CI/unit tests:
- no network calls
- no GCP client construction

Cloud Run entrypoints may override these module globals at runtime.
"""

from __future__ import annotations

import os


def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name) or str(default)).strip())
    except Exception:
        return default


# Core identifiers (default empty; entrypoints may override on boot)
PROJECT_ID: str = (os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()

# Pub/Sub topics (ids or fully-qualified names depending on deployment conventions)
SYSTEM_EVENTS_TOPIC: str = (os.getenv("SYSTEM_EVENTS_TOPIC") or "").strip()
MARKET_TICKS_TOPIC: str = (os.getenv("MARKET_TICKS_TOPIC") or "").strip()
MARKET_BARS_1M_TOPIC: str = (os.getenv("MARKET_BARS_1M_TOPIC") or "").strip()
TRADE_SIGNALS_TOPIC: str = (os.getenv("TRADE_SIGNALS_TOPIC") or "").strip()

# Feature-flag secret id (lookup is done elsewhere; this module only stores the id)
INGEST_FLAG_SECRET_ID: str = (os.getenv("INGEST_FLAG_SECRET_ID") or "").strip()

# Loop timing defaults (kept conservative for tests/CI)
HEARTBEAT_INTERVAL_SECONDS: int = max(1, _env_int("HEARTBEAT_INTERVAL_SECONDS", 15))
FLAG_CHECK_INTERVAL_SECONDS: int = max(1, _env_int("FLAG_CHECK_INTERVAL_SECONDS", 60))

