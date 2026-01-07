"""
DEPRECATED: use `backend.time.nyse_time` and `backend.time.providers`.

This module remains as a thin back-compat shim to avoid breaking older imports.
All logic delegates to the single source of truth under `backend/time/`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.time import nyse_time as _nyse_time
from backend.time.providers import normalize_alpaca_timestamp

UTC = _nyse_time.UTC
NYSE_TZ = _nyse_time.NYSE_TZ


def parse_alpaca_timestamp(value: Any) -> datetime:
    return normalize_alpaca_timestamp(value)


def to_nyse_time(value: Any) -> datetime:
    return normalize_alpaca_timestamp(value).astimezone(NYSE_TZ)


def to_utc_time(value: Any) -> datetime:
    return normalize_alpaca_timestamp(value).astimezone(UTC)


def nyse_isoformat(value: Any, timespec: str = "milliseconds") -> str:
    return to_nyse_time(value).isoformat(timespec=timespec)


# ---------------------------------------------------------------------------
# Back-compat aliases (used across the existing backend + tests)
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return tz-aware current time in UTC."""

    return _nyse_time.utc_now()


def ensure_aware_utc(value: datetime) -> datetime:
    """
    Ensure a datetime is tz-aware and normalized to UTC.
    Naive datetimes are assumed to be UTC.
    """

    return _nyse_time.ensure_aware_utc(value)


def parse_timestamp(value: Any) -> datetime:
    """
    Back-compat timestamp parser used across the repo.
    Delegates to the canonical Alpaca timestamp parser.
    """

    return _nyse_time.parse_ts(value)

