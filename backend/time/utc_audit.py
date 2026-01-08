"""
UTC timestamp enforcement + audit logging (non-breaking).

Goals:
- Validate timestamps are tz-aware UTC at boundaries.
- Detect naive datetime usage (tzinfo missing / utcoffset unavailable).
- Log when timestamps are auto-corrected (naive->UTC attach, non-UTC->UTC convert).

This module is dependency-light by design: it uses stdlib `logging` only and avoids
importing heavier observability stacks so it can be safely used from core time utils.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional

_LOGGER = logging.getLogger("timestamp_audit")

_LOCK = threading.Lock()
_COUNTS: dict[tuple[str, str, str], int] = {}


def _bool_env(name: str, default: bool = True) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(str(v).strip())
    except Exception:
        return default


def _should_log(*, kind: str, source: str, field: str) -> bool:
    if not _bool_env("TIMESTAMP_AUDIT_LOGGING_ENABLED", True):
        return False

    limit = max(0, _int_env("TIMESTAMP_AUDIT_LOG_LIMIT_PER_KEY", 5))
    if limit == 0:
        return False

    key = (str(kind), str(source), str(field))
    with _LOCK:
        cur = _COUNTS.get(key, 0)
        if cur >= limit:
            return False
        _COUNTS[key] = cur + 1
        return True


def _safe_iso(dt: datetime) -> str:
    try:
        return dt.isoformat()
    except Exception:
        return "<unprintable-datetime>"


def ensure_utc(
    dt: datetime,
    *,
    source: str = "unknown",
    field: str = "timestamp",
    utc_tz: tzinfo = timezone.utc,
) -> datetime:
    """
    Ensure `dt` is tz-aware and normalized to UTC (or a UTC-equivalent tzinfo).

    Non-breaking behavior:
    - Naive datetimes are assumed to already represent UTC (canonical rule in this repo).
    - Aware non-UTC datetimes are converted to UTC.

    Logging:
    - Emits a warning the first N times per (kind, source, field) when auto-correcting.
    """
    if not isinstance(dt, datetime):
        raise TypeError("ensure_utc expects a datetime")

    # Treat "no tzinfo" and "utcoffset unavailable" as naive / invalid tz.
    offset = dt.tzinfo.utcoffset(dt) if dt.tzinfo is not None else None
    if dt.tzinfo is None or offset is None:
        corrected = dt.replace(tzinfo=utc_tz)
        if _should_log(kind="naive_assumed_utc", source=source, field=field):
            _LOGGER.warning(
                "timestamp.naive_assumed_utc",
                extra={
                    "event_type": "timestamp.naive_assumed_utc",
                    "source": source,
                    "field": field,
                    "original": _safe_iso(dt),
                    "corrected": _safe_iso(corrected),
                },
            )
        return corrected

    corrected = dt.astimezone(utc_tz)
    # Only log when the input offset is actually non-zero (true non-UTC).
    if offset != timedelta(0):
        if _should_log(kind="converted_to_utc", source=source, field=field):
            _LOGGER.warning(
                "timestamp.converted_to_utc",
                extra={
                    "event_type": "timestamp.converted_to_utc",
                    "source": source,
                    "field": field,
                    "original": _safe_iso(dt),
                    "corrected": _safe_iso(corrected),
                    "original_offset_seconds": float(offset.total_seconds()),
                },
            )
    return corrected


__all__ = ["ensure_utc"]

