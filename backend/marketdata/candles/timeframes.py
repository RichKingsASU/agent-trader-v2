from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from backend.common.timeutils import UTC, ensure_aware_utc


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

    text = normalize_timeframe_text(unit, step)
    tf = Timeframe(unit=unit, step=step, text=text)
    validate_timeframe(tf)
    return tf


def normalize_timeframe_text(unit: str, step: int) -> str:
    unit = unit.lower()
    if unit == "mo":
        return f"{step}mo"
    return f"{step}{unit}"


def validate_timeframe(tf: Timeframe) -> None:
    allowed: dict[str, set[int]] = {
        "s": {1, 5, 10, 15, 30},
        "m": {1, 2, 3, 4, 5, 10, 15, 20, 30, 45},
        "h": {1, 2, 3, 4},
        "d": {1},
        "w": {1},
        "mo": {1},
    }
    if tf.unit not in allowed or tf.step not in allowed[tf.unit]:
        raise ValueError(f"Unsupported timeframe: {tf.text}")


def parse_timeframes(values: Iterable[str]) -> list[Timeframe]:
    return [parse_timeframe(v) for v in values]


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
    - Optional: session_daily=True aligns daily candles to NY RTH session start (09:30).
    """
    ts_utc = ensure_aware_utc(ts_utc)

    if tf.unit in {"s", "m", "h"}:
        sec = tf.seconds
        epoch = int(ts_utc.timestamp())
        start_epoch = epoch - (epoch % sec)
        start = datetime.fromtimestamp(start_epoch, tz=UTC)
        end = start + timedelta(seconds=sec)
        return start, end

    tz = ZoneInfo(tz_market)
    ts_local = ts_utc.astimezone(tz)

    if tf.unit == "d":
        if session_daily:
            # NY RTH session start boundary (09:30); key by session "date".
            # If before 09:30 local, treat it as previous session day.
            session_start = ts_local.replace(hour=9, minute=30, second=0, microsecond=0)
            if ts_local < session_start:
                prev = ts_local - timedelta(days=1)
                session_start = prev.replace(hour=9, minute=30, second=0, microsecond=0)
            start_local = session_start
            end_local = (start_local + timedelta(days=1)).replace(
                hour=9, minute=30, second=0, microsecond=0
            )
        else:
            start_local = ts_local.replace(hour=0, minute=0, second=0, microsecond=0)
            end_local = start_local + timedelta(days=1)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    if tf.unit == "w":
        # Week starts Monday 00:00 local time.
        start_of_day = ts_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_local = start_of_day - timedelta(days=start_of_day.weekday())
        end_local = start_local + timedelta(days=7)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    if tf.unit == "mo":
        start_local = ts_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_local.month == 12:
            next_local = start_local.replace(year=start_local.year + 1, month=1)
        else:
            next_local = start_local.replace(month=start_local.month + 1)
        return start_local.astimezone(UTC), next_local.astimezone(UTC)

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

