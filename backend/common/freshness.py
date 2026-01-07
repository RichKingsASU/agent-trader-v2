"""
Market data freshness helpers (fail-closed).

This module is intentionally dependency-free and pure: it does not perform any IO.

Contract:
- Freshness is derived from the latest known market-data event timestamp (tick/bar close).
- If freshness cannot be determined (missing timestamp), we treat it as STALE.
- Callers should refuse to evaluate strategies when STALE (NOOP + structured log).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Protocol


class HasTimestamp(Protocol):
    ts: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def coerce_utc(ts: datetime) -> tuple[datetime, bool]:
    """
    Return (ts_utc, assumed_utc).

    - If `ts` is naive, we assume it is already UTC (fail-closed callers should
      still treat large ages as STALE).
    - If `ts` is timezone-aware, it is converted to UTC.
    """
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        return ts.replace(tzinfo=timezone.utc), True
    return ts.astimezone(timezone.utc), False


def latest_timestamp(items: Iterable[HasTimestamp]) -> Optional[datetime]:
    """
    Extract the latest `.ts` from an iterable of objects.

    Returns None if the iterable is empty.
    """
    latest: datetime | None = None
    for it in items:
        ts = getattr(it, "ts", None)
        if not isinstance(ts, datetime):
            continue
        latest = ts if latest is None or ts > latest else latest
    return latest


def stale_after_for_bar_interval(*, bar_interval: timedelta, multiplier: float = 2.0) -> timedelta:
    """
    Recommended staleness threshold for bar-based strategies: `multiplier * bar_interval`.
    """
    if multiplier <= 0:
        multiplier = 2.0
    seconds = max(0.0, float(bar_interval.total_seconds()) * float(multiplier))
    return timedelta(seconds=seconds)


@dataclass(frozen=True, slots=True)
class FreshnessCheck:
    ok: bool
    reason_code: str  # "FRESH" | "STALE_DATA" | "MISSING_TIMESTAMP"
    latest_ts_utc: datetime | None
    now_utc: datetime
    age: timedelta | None
    stale_after: timedelta
    details: dict[str, Any]


def check_freshness(
    *,
    latest_ts: datetime | None,
    stale_after: timedelta,
    now: datetime | None = None,
    source: str = "unknown",
) -> FreshnessCheck:
    """
    Evaluate freshness from a latest event timestamp.

    `ok == True` means the timestamp is present and age <= stale_after.
    """
    now_utc = coerce_utc(now or utc_now())[0]
    if latest_ts is None:
        return FreshnessCheck(
            ok=False,
            reason_code="MISSING_TIMESTAMP",
            latest_ts_utc=None,
            now_utc=now_utc,
            age=None,
            stale_after=stale_after,
            details={"source": source},
        )

    latest_utc, assumed_utc = coerce_utc(latest_ts)
    age = now_utc - latest_utc
    # If clocks are skewed and age is negative, treat as fresh but report it.
    ok = age <= stale_after
    reason = "FRESH" if ok else "STALE_DATA"

    return FreshnessCheck(
        ok=ok,
        reason_code=reason,
        latest_ts_utc=latest_utc,
        now_utc=now_utc,
        age=age,
        stale_after=stale_after,
        details={
            "source": source,
            "assumed_utc": assumed_utc,
            "age_seconds": float(age.total_seconds()),
            "threshold_seconds": float(stale_after.total_seconds()),
        },
    )

