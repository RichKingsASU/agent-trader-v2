"""
Single source of truth for timestamp parsing and NYSE (America/New_York) time logic.

Canonical rules:
- **Internal storage**: tz-aware UTC datetimes.
- **NYSE bucketing / session logic**: convert to America/New_York only when needed.

No hard-coded offsets (EST/EDT). Uses `zoneinfo` DST rules.

Exchange calendar support:
- If `USE_EXCHANGE_CALENDAR=true` and `exchange_calendars` is installed, NYSE holidays
  and special sessions are handled accurately.
- Otherwise, a documented fallback is used: weekday-only, 09:30–16:00 NY time.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
NYSE_TZ = ZoneInfo("America/New_York")

# Numeric string epochs (seconds or ms) appear in some payloads/logs.
_NUMERIC_EPOCH_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")

# Feature flag for calendar-aware sessions.
USE_EXCHANGE_CALENDAR = str(os.getenv("USE_EXCHANGE_CALENDAR", "true")).strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _duck_to_datetime(value: Any) -> Optional[datetime]:
    """
    Best-effort conversion for common timestamp objects without importing heavy deps.

    Supported duck-typed shapes:
    - pandas.Timestamp: implements `.to_pydatetime()`
    - Firestore Timestamp: implements `.to_datetime()`
    """

    to_py = getattr(value, "to_pydatetime", None)
    if callable(to_py):
        try:
            dt = to_py()
            if isinstance(dt, datetime):
                return dt
        except Exception:
            return None

    to_dt = getattr(value, "to_datetime", None)
    if callable(to_dt):
        try:
            dt = to_dt()
            if isinstance(dt, datetime):
                return dt
        except Exception:
            return None

    return None


def parse_ts(x: Any) -> datetime:
    """
    Parse provider timestamps into a tz-aware UTC datetime.

    Supports:
    - `datetime` (naive treated as UTC)
    - ISO strings (with or without 'Z' / offset; naive treated as UTC)
    - epoch seconds (int/float)
    - epoch milliseconds (int; heuristic: abs(value) >= 1e12)
    """

    if x is None:
        raise TypeError("timestamp is None")

    # Optional duck-typed conversions (pandas/firestore/etc.)
    dt_duck = _duck_to_datetime(x)
    if dt_duck is not None:
        x = dt_duck

    if isinstance(x, datetime):
        dt = x
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    if isinstance(x, (int, float)):
        v = float(x)
        seconds = (v / 1000.0) if abs(v) >= 1e12 else v
        return datetime.fromtimestamp(seconds, tz=UTC)

    if isinstance(x, str):
        s = x.strip()
        if not s:
            raise ValueError("timestamp string is empty")
        if _NUMERIC_EPOCH_RE.match(s):
            return parse_ts(float(s))
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"unparseable timestamp string: {x!r}") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    raise TypeError(f"unsupported timestamp type: {type(x).__name__}")


def to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to tz-aware UTC. Naive datetimes are assumed UTC."""

    if not isinstance(dt, datetime):
        raise TypeError("to_utc expects a datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_nyse(dt: datetime) -> datetime:
    """Convert a datetime to tz-aware America/New_York. Naive datetimes are assumed UTC."""

    return to_utc(dt).astimezone(NYSE_TZ)


def utc_now() -> datetime:
    """Return current tz-aware UTC time."""

    return datetime.now(tz=UTC)


def ensure_aware_utc(dt: datetime) -> datetime:
    """Alias for `to_utc` (kept for back-compat across the repo)."""

    return to_utc(dt)


# ---------------------------------------------------------------------------
# NYSE trading session helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CalendarBackend:
    name: str
    cal: Any


_CAL: _CalendarBackend | None = None


def exchange_calendar_available() -> bool:
    """True iff `exchange_calendars` can be imported in this environment."""

    try:
        import exchange_calendars  # noqa: F401

        return True
    except Exception:
        return False


def _get_calendar_backend() -> _CalendarBackend | None:
    global _CAL
    if _CAL is not None:
        return _CAL

    if not USE_EXCHANGE_CALENDAR or not _bool_env("USE_EXCHANGE_CALENDAR", True):
        _CAL = None
        return None

    try:
        import exchange_calendars as xcals

        _CAL = _CalendarBackend(name="exchange_calendars", cal=xcals.get_calendar("XNYS"))
        return _CAL
    except Exception:
        _CAL = None
        return None


def _as_ny_date(d: date | datetime) -> date:
    if isinstance(d, datetime):
        return to_nyse(d).date()
    if isinstance(d, date):
        return d
    raise TypeError("date_ny must be a date or datetime")


def is_trading_day(date_ny: date | datetime) -> bool:
    """
    True if NYSE is open for a regular session on the given NY date.

    Fallback (no exchange calendar): Mon–Fri only (does NOT account for holidays).
    """

    d = _as_ny_date(date_ny)
    backend = _get_calendar_backend()
    if backend is None:
        return d.weekday() < 5

    # exchange_calendars uses pandas sessions under the hood; keep imports local.
    import pandas as pd

    return bool(backend.cal.is_session(pd.Timestamp(d)))


def market_open_dt(date_ny: date | datetime) -> datetime:
    """
    Market open for a given NY date, returned as tz-aware America/New_York datetime.

    Fallback (no exchange calendar): 09:30 local time.
    """

    d = _as_ny_date(date_ny)
    backend = _get_calendar_backend()
    if backend is None:
        return datetime.combine(d, time(9, 30), tzinfo=NYSE_TZ)

    import pandas as pd

    open_utc = backend.cal.session_open(pd.Timestamp(d))
    return to_nyse(open_utc.to_pydatetime())


def market_close_dt(date_ny: date | datetime) -> datetime:
    """
    Market close for a given NY date, returned as tz-aware America/New_York datetime.

    Fallback (no exchange calendar): 16:00 local time.
    """

    d = _as_ny_date(date_ny)
    backend = _get_calendar_backend()
    if backend is None:
        return datetime.combine(d, time(16, 0), tzinfo=NYSE_TZ)

    import pandas as pd

    close_utc = backend.cal.session_close(pd.Timestamp(d))
    return to_nyse(close_utc.to_pydatetime())


def is_market_open(now_dt_utc_or_ny: datetime) -> bool:
    """True if `now` is within regular trading hours for its NY trading day."""

    now_utc = to_utc(now_dt_utc_or_ny)
    now_ny = now_utc.astimezone(NYSE_TZ)
    d = now_ny.date()
    if not is_trading_day(d):
        return False
    o = market_open_dt(d)
    c = market_close_dt(d)
    return o <= now_ny < c


def next_open(now_dt_utc_or_ny: datetime) -> datetime:
    """
    Next NYSE regular-session open after `now`, returned in NY tz.
    """

    now_ny = to_nyse(now_dt_utc_or_ny)
    d = now_ny.date()
    if is_trading_day(d):
        o = market_open_dt(d)
        if now_ny < o:
            return o

    # Walk forward by day.
    d2 = d + timedelta(days=1)
    while not is_trading_day(d2):
        d2 = d2 + timedelta(days=1)
    return market_open_dt(d2)


def previous_close(now_dt_utc_or_ny: datetime) -> datetime:
    """
    Most recent NYSE regular-session close at or before `now`, returned in NY tz.
    """

    now_ny = to_nyse(now_dt_utc_or_ny)
    d = now_ny.date()
    if is_trading_day(d):
        c = market_close_dt(d)
        if now_ny >= c:
            return c

    d2 = d - timedelta(days=1)
    while not is_trading_day(d2):
        d2 = d2 - timedelta(days=1)
    return market_close_dt(d2)


# ---------------------------------------------------------------------------
# Candle bucketing utilities
# ---------------------------------------------------------------------------


_TF_RE = re.compile(r"^\s*(\d+)?\s*([a-zA-Z]+)\s*$")


def timeframe_to_timedelta(timeframe: str) -> timedelta:
    """
    Convert common timeframe strings to a timedelta.

    Supports:
    - seconds:  '1s','5s','15s','30s'
    - minutes:  '1m','5m','15m','30m'
    - hours:    '1h','2h','4h'
    - day:      '1d'/'1D'

    Note: calendar units like weeks/months have variable duration and are not supported here.
    """

    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe must be a non-empty string")

    upper = timeframe.strip().upper()
    if upper == "D":
        return timedelta(days=1)

    m = _TF_RE.match(timeframe)
    if not m:
        raise ValueError(f"invalid timeframe: {timeframe!r}")

    step_s, unit_s = m.group(1), m.group(2)
    step = int(step_s) if step_s is not None else 1
    unit = unit_s.strip().lower()

    if unit in {"s", "sec", "secs", "second", "seconds"}:
        return timedelta(seconds=step)
    if unit in {"m", "min", "mins", "minute", "minutes"}:
        return timedelta(minutes=step)
    if unit in {"h", "hr", "hrs", "hour", "hours"}:
        return timedelta(hours=step)
    if unit in {"d", "day", "days"}:
        return timedelta(days=step)

    raise ValueError(f"unsupported timeframe unit for timedelta: {timeframe!r}")


def _parse_tf(timeframe: str) -> tuple[int, str]:
    if not isinstance(timeframe, str) or not timeframe.strip():
        raise ValueError("timeframe must be a non-empty string")

    upper = timeframe.strip().upper()
    if upper == "D":
        return 1, "d"

    m = _TF_RE.match(timeframe)
    if not m:
        raise ValueError(f"invalid timeframe: {timeframe!r}")

    step_s, unit_s = m.group(1), m.group(2)
    step = int(step_s) if step_s is not None else 1
    unit = unit_s.strip().lower()

    # Normalize "1D" -> ("d")
    if unit == "d":
        return step, "d"
    if unit == "w":
        return step, "w"
    if unit == "mo":
        return step, "mo"
    if unit in {"s", "m", "h"}:
        return step, unit
    if unit in {"sec", "secs", "second", "seconds"}:
        return step, "s"
    if unit in {"min", "mins", "minute", "minutes"}:
        return step, "m"
    if unit in {"hr", "hrs", "hour", "hours"}:
        return step, "h"
    if unit in {"day", "days"}:
        return step, "d"
    if unit in {"week", "weeks", "wk", "wks"}:
        return step, "w"
    if unit in {"month", "months", "mon", "mons", "mth", "mths"}:
        return step, "mo"

    raise ValueError(f"invalid timeframe unit: {timeframe!r}")


def floor_to_timeframe(dt_utc_or_ny: datetime, timeframe: str, tz: str = "America/New_York") -> datetime:
    """
    Floor a datetime to a timeframe boundary in the specified timezone.

    Returns the floored boundary as a tz-aware datetime in `tz`.
    """

    step, unit = _parse_tf(timeframe)
    tzinfo = ZoneInfo(tz)

    dt_local = to_utc(dt_utc_or_ny).astimezone(tzinfo)

    if unit == "s":
        if step <= 0:
            raise ValueError("timeframe step must be > 0")
        base = dt_local.replace(microsecond=0)
        sec = (base.second // step) * step
        return base.replace(second=sec)

    if unit == "m":
        if step <= 0:
            raise ValueError("timeframe step must be > 0")
        base = dt_local.replace(second=0, microsecond=0)
        minute = (base.minute // step) * step
        return base.replace(minute=minute)

    if unit == "h":
        if step <= 0:
            raise ValueError("timeframe step must be > 0")
        base = dt_local.replace(minute=0, second=0, microsecond=0)
        hour = (base.hour // step) * step
        return base.replace(hour=hour)

    if unit == "d":
        if step <= 0:
            raise ValueError("timeframe step must be > 0")
        # Step > 1: align to an epoch day boundary within tz (date arithmetic).
        d0 = dt_local.date()
        if step == 1:
            return datetime.combine(d0, time(0, 0), tzinfo=tzinfo)
        # Align to multiples of `step` since 1970-01-01 in this tz.
        epoch = date(1970, 1, 1)
        days = (d0 - epoch).days
        aligned = days - (days % step)
        d_aligned = epoch + timedelta(days=aligned)
        return datetime.combine(d_aligned, time(0, 0), tzinfo=tzinfo)

    if unit == "w":
        if step != 1:
            raise ValueError("weekly bucketing only supports step=1")
        d0 = dt_local.date()
        start = d0 - timedelta(days=d0.weekday())  # Monday
        return datetime.combine(start, time(0, 0), tzinfo=tzinfo)

    if unit == "mo":
        if step != 1:
            raise ValueError("monthly bucketing only supports step=1")
        d0 = dt_local.date()
        return datetime(d0.year, d0.month, 1, 0, 0, 0, tzinfo=tzinfo)

    raise ValueError(f"unhandled timeframe: {timeframe!r}")


def ceil_to_timeframe(dt_utc_or_ny: datetime, timeframe: str, tz: str = "America/New_York") -> datetime:
    """
    Ceil a datetime to a timeframe boundary in the specified timezone.

    Returns the ceiled boundary as a tz-aware datetime in `tz`.
    """

    step, unit = _parse_tf(timeframe)
    tzinfo = ZoneInfo(tz)
    dt_local = to_utc(dt_utc_or_ny).astimezone(tzinfo)
    flo = floor_to_timeframe(dt_local, timeframe, tz=tz)

    # If already on boundary (down to microsecond), return flo.
    if dt_local == flo:
        return flo

    if unit in {"s", "m", "h"}:
        return flo + timeframe_to_timedelta(timeframe)

    if unit == "d":
        d = flo.date() + timedelta(days=step)
        return datetime.combine(d, time(0, 0), tzinfo=tzinfo)

    if unit == "w":
        d = flo.date() + timedelta(days=7)
        return datetime.combine(d, time(0, 0), tzinfo=tzinfo)

    if unit == "mo":
        y, m = flo.year, flo.month
        if m == 12:
            y2, m2 = y + 1, 1
        else:
            y2, m2 = y, m + 1
        return datetime(y2, m2, 1, 0, 0, 0, tzinfo=tzinfo)

    raise ValueError(f"unhandled timeframe: {timeframe!r}")


__all__ = [
    "UTC",
    "NYSE_TZ",
    "USE_EXCHANGE_CALENDAR",
    "parse_ts",
    "to_utc",
    "to_nyse",
    "utc_now",
    "ensure_aware_utc",
    "exchange_calendar_available",
    "is_trading_day",
    "market_open_dt",
    "market_close_dt",
    "is_market_open",
    "next_open",
    "previous_close",
    "timeframe_to_timedelta",
    "floor_to_timeframe",
    "ceil_to_timeframe",
]

