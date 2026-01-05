"""
Canonical Alpaca timestamp normalization helpers.

Design:
- **Storage**: keep timestamps as tz-aware UTC (`TIMESTAMPTZ`) for DB consistency.
- **Display / market-hours logic**: convert to NYSE local time (`America/New_York`).

Rules:
- Naive `datetime` (no tzinfo) is assumed to be **UTC**.
- ISO8601 strings ending with 'Z' are treated as UTC.
- ISO8601 strings with an offset preserve that offset and convert correctly.
- Numeric epoch: values >= 1e12 are treated as milliseconds, otherwise seconds.

No hard-coded offsets (EST/EDT). Uses `zoneinfo` DST rules.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
NYSE_TZ = ZoneInfo("America/New_York")


def _as_datetime_from_pandas(value: Any) -> Optional[datetime]:
    """
    Best-effort conversion for pandas Timestamp without importing pandas globally.
    Returns None if `value` does not look like a pandas Timestamp.
    """

    # Duck-typing: pandas.Timestamp implements .to_pydatetime()
    to_py = getattr(value, "to_pydatetime", None)
    if callable(to_py):
        try:
            out = to_py()
            if isinstance(out, datetime):
                return out
        except Exception:
            return None
    return None


def parse_alpaca_timestamp(value: Any) -> datetime:
    """
    Parse common Alpaca timestamp shapes into a tz-aware UTC datetime.

    Supported input shapes:
    - ISO8601 strings (e.g. '2025-01-02T14:30:00Z', '...-05:00', '...+00:00')
    - `datetime` (naive or tz-aware)
    - epoch seconds or milliseconds (int/float)
    - pandas Timestamp (if pandas is installed; detected via `.to_pydatetime()`)
    """

    if value is None:
        raise TypeError("timestamp value is None")

    # pandas.Timestamp (optional dependency)
    pd_dt = _as_datetime_from_pandas(value)
    if pd_dt is not None:
        value = pd_dt

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            # Canonical assumption: naive datetimes are UTC.
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    if isinstance(value, (int, float)):
        # Epoch seconds vs milliseconds heuristic
        v = float(value)
        seconds = (v / 1000.0) if abs(v) >= 1e12 else v
        return datetime.fromtimestamp(seconds, tz=UTC)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("timestamp string is empty")

        # Alpaca commonly uses a trailing 'Z' for UTC.
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"

        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"unparseable timestamp string: {value!r}") from e

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    raise TypeError(f"unsupported timestamp type: {type(value).__name__}")


def to_nyse_time(value: Any) -> datetime:
    """Convert a supported timestamp input to NYSE local time (tz-aware)."""

    return parse_alpaca_timestamp(value).astimezone(NYSE_TZ)


def to_utc_time(value: Any) -> datetime:
    """Convert a supported timestamp input to UTC (tz-aware)."""

    return parse_alpaca_timestamp(value).astimezone(UTC)


def nyse_isoformat(value: Any, timespec: str = "milliseconds") -> str:
    """
    Return an ISO8601 string in NYSE local time, including offset.
    Example: '2025-01-02T09:30:00.000-05:00'
    """

    return to_nyse_time(value).isoformat(timespec=timespec)


# ---------------------------------------------------------------------------
# Back-compat aliases (used across the existing backend + tests)
# ---------------------------------------------------------------------------


def utc_now() -> datetime:
    """Return tz-aware current time in UTC."""

    return datetime.now(tz=UTC)


def ensure_aware_utc(value: datetime) -> datetime:
    """
    Ensure a datetime is tz-aware and normalized to UTC.
    Naive datetimes are assumed to be UTC.
    """

    if not isinstance(value, datetime):
        raise TypeError("ensure_aware_utc expects a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_timestamp(value: Any) -> datetime:
    """
    Back-compat timestamp parser used across the repo.
    Delegates to the canonical Alpaca timestamp parser.
    """

    return parse_alpaca_timestamp(value)

