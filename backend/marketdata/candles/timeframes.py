from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from backend.time.nyse_time import (
    UTC,
    ceil_to_timeframe,
    ensure_aware_utc,
    floor_to_timeframe,
    market_open_dt,
    next_open,
    to_nyse,
)


@dataclass(frozen=True, slots=True)
class Timeframe:
    """
    Normalized candle timeframe.

    Normalized text values match the DB representation:
      - seconds:  '1s','5s','10s','15s','30s'
      - minutes:  '1m','2m','3m','4m','5m','10m','15m','20m','30m','45m'
      - hours:    '1h','2h','3h','4h'
      - day:      '1d'
      - week:     '1w'
      - month:    '1mo'
    """

    unit: str  # "s" | "m" | "h" | "d" | "w" | "mo"
    step: int
    text: str

    @property
    def is_intraday(self) -> bool:
        return self.unit in {"s", "m", "h"}

    @property
    def seconds(self) -> int:
        if self.unit == "s":
            return self.step
        if self.unit == "m":
            return self.step * 60
        if self.unit == "h":
            return self.step * 3600
        raise ValueError("Non-intraday timeframe has variable duration")


_TF_RE = re.compile(r"^\s*(\d+)?\s*([a-zA-Z]+)\s*$")


def parse_timeframe(value: str) -> Timeframe:
    """
    Parse timeframe strings like:
      '15s','1m','2h','1d','1w','1mo'
    Also accepts TradingView-ish shorthands:
      'D' -> '1d', 'W' -> '1w', 'M' -> '1mo'
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timeframe must be a non-empty string")

    upper = value.strip().upper()
    if upper == "D":
        unit, step = "d", 1
    elif upper == "W":
        unit, step = "w", 1
    elif upper == "M":
        unit, step = "mo", 1
    else:
        m = _TF_RE.match(value)
        if not m:
            raise ValueError(f"Invalid timeframe: {value!r}")

        step_s, unit_s = m.group(1), m.group(2)
        step = int(step_s) if step_s is not None else 1
        unit_raw = unit_s.strip().lower()

        # Normalize unit tokens
        if unit_raw in {"sec", "secs", "second", "seconds", "s"}:
            unit = "s"
        elif unit_raw in {"min", "mins", "minute", "minutes", "m"}:
            unit = "m"
        elif unit_raw in {"hr", "hrs", "hour", "hours", "h"}:
            unit = "h"
        elif unit_raw in {"d", "day", "days"}:
            unit = "d"
        elif unit_raw in {"w", "wk", "wks", "week", "weeks"}:
            unit = "w"
        elif unit_raw in {"mo", "mon", "mons", "month", "months", "mth", "mths"}:
            unit = "mo"
        else:
            raise ValueError(f"Invalid timeframe unit: {value!r}")






def bucket_range_utc(
    ts_utc: datetime,
    tf: Timeframe,
    *,
    tz_market: str = "America/New_York",
    session_daily: bool = False,
) -> tuple[datetime, datetime]:
    """
    Returns (ts_start_utc, ts_end_utc) for the candle bucket containing ts_utc.

    Alignment rules:
    - Intraday (S/M/H): floor in UTC.
    - D/W/M: align by market timezone (default America/New_York) boundaries.
           - Optional: session_daily=True aligns daily candles to NY RTH session start (9:30).    """
    ts_utc = ensure_aware_utc(ts_utc)

    if tf.unit in {"s", "m", "h"}:
        start = floor_to_timeframe(ts_utc, tf.text, tz="UTC").astimezone(UTC)
        end = start + timedelta(seconds=tf.seconds)
        return start, end

    if tf.unit == "d":
        if session_daily:
            # NY RTH session start boundary (09:30). Uses the canonical NYSE session helpers.
            # If `exchange_calendars` is available + enabled, this also respects holidays.
            ts_ny = to_nyse(ts_utc)
            open_today = market_open_dt(ts_ny.date())
            session_date = ts_ny.date() if ts_ny >= open_today else (ts_ny.date() - timedelta(days=1))
            start_local = market_open_dt(session_date)
            end_local = next_open(start_local + timedelta(seconds=1))
        else:
            start_local = floor_to_timeframe(ts_utc, tf.text, tz=tz_market)
            end_local = ceil_to_timeframe(ts_utc, tf.text, tz=tz_market)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    if tf.unit == "w":
        start_local = floor_to_timeframe(ts_utc, tf.text, tz=tz_market)
        end_local = ceil_to_timeframe(ts_utc, tf.text, tz=tz_market)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    if tf.unit == "mo":
        start_local = floor_to_timeframe(ts_utc, tf.text, tz=tz_market)
        end_local = ceil_to_timeframe(ts_utc, tf.text, tz=tz_market)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    raise ValueError(f"Unhandled timeframe: {tf.text}")


SUPPORTED_TIMEFRAMES: tuple[str, ...] = (
    "1s",
    "5s",
    "10s",
    "15s",
    "30s",
    "1m",
    "2m",
    "3m",
    "4m",
    "5m",
    "10m",
    "15m",
    "20m",
    "30m",
    "45m",
    "1h",
    "2h",
    "3h",
    "4h",
    "1d",
    "1w",
    "1mo",
)

