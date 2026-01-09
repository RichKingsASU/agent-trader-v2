"""
UTC timestamp enforcement + audit logging (Cloud Run consumer).

This service uses lightweight JSON-print logging; we keep this module self-contained
to avoid introducing dependencies or changing existing logging infrastructure.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import logging

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _emit(event_type: str, *, severity: str = "WARNING", **fields: Any) -> None:
    # Prefer the repo-wide structured logger when available.
    try:
        from backend.common.logging import log_standard_event  # noqa: WPS433

        log_standard_event(
            logging.getLogger("cloudrun_consumer.time_audit"),
            str(event_type),
            severity=str(severity).upper(),
            outcome="corrected",
            **fields,
        )
    except Exception:
        payload: dict[str, Any] = {
            "timestamp": _utc_now_iso(),
            "severity": str(severity).upper(),
            "event_type": str(event_type),
        }
        payload.update(fields)
        try:
            print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)
        except Exception:
            return


def ensure_utc(
    dt: datetime,
    *,
    source: str = "unknown",
    field: str = "timestamp",
) -> datetime:
    """
    Ensure tz-aware UTC datetime (non-breaking).

    - Naive datetimes are assumed UTC.
    - Aware non-UTC datetimes are converted to UTC.
    - Logs when auto-corrections happen (rate-limited).
    """
    if not isinstance(dt, datetime):
        raise TypeError("ensure_utc expects a datetime")

    offset = dt.tzinfo.utcoffset(dt) if dt.tzinfo is not None else None
    if dt.tzinfo is None or offset is None:
        corrected = dt.replace(tzinfo=timezone.utc)
        if _should_log(kind="naive_assumed_utc", source=source, field=field):
            _emit(
                "timestamp.naive_assumed_utc",
                source=source,
                field=field,
                original=str(dt),
                corrected=corrected.isoformat(),
            )
        return corrected

    corrected = dt.astimezone(timezone.utc)
    if offset != timedelta(0):
        if _should_log(kind="converted_to_utc", source=source, field=field):
            _emit(
                "timestamp.converted_to_utc",
                source=source,
                field=field,
                original=dt.isoformat(),
                corrected=corrected.isoformat(),
                original_offset_seconds=float(offset.total_seconds()),
            )
    return corrected


__all__ = ["ensure_utc"]

