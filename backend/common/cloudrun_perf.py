"""
Cloud Run / process-level performance markers (logging-only).

This module is intentionally stdlib-only and safe to import anywhere.

Signals:
- cold_start vs warm_start: first request handled by this process (instance)
- time-to-first-publish: first successful publish call in this process
- instance_uptime_ms: monotonic uptime since module import
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


_INSTANCE_START_MONO: float = time.monotonic()
_INSTANCE_START_UTC: str = _utc_ts()

_lock = threading.Lock()
_request_count: int = 0
_first_publish_marked: bool = False


@dataclass(frozen=True)
class RequestClassification:
    request_ordinal: int
    cold_start: bool
    instance_uptime_ms: int


@dataclass(frozen=True)
class FirstPublishMarker:
    first_publish: bool
    time_to_first_publish_ms: Optional[int]
    instance_uptime_ms: int


def instance_start_utc() -> str:
    return _INSTANCE_START_UTC


def instance_uptime_ms() -> int:
    return int(max(0.0, (time.monotonic() - _INSTANCE_START_MONO) * 1000.0))


def classify_request() -> RequestClassification:
    """
    Increment and classify this process' request ordinal.
    """
    global _request_count
    with _lock:
        _request_count += 1
        ordinal = int(_request_count)
    return RequestClassification(
        request_ordinal=ordinal,
        cold_start=(ordinal == 1),
        instance_uptime_ms=instance_uptime_ms(),
    )


def mark_first_publish() -> FirstPublishMarker:
    """
    Mark and return whether this is the first successful publish in-process.
    """
    global _first_publish_marked
    uptime_ms = instance_uptime_ms()
    with _lock:
        if _first_publish_marked:
            return FirstPublishMarker(first_publish=False, time_to_first_publish_ms=None, instance_uptime_ms=uptime_ms)
        _first_publish_marked = True
        return FirstPublishMarker(first_publish=True, time_to_first_publish_ms=uptime_ms, instance_uptime_ms=uptime_ms)


def identity_fields() -> dict[str, Any]:
    """
    Stable-ish identity fields useful in logs for grouping.
    """
    return {
        "pid": os.getpid(),
        "k_service": os.getenv("K_SERVICE") or "",
        "k_revision": os.getenv("K_REVISION") or "",
        "k_configuration": os.getenv("K_CONFIGURATION") or "",
        "instance_start_utc": _INSTANCE_START_UTC,
    }

