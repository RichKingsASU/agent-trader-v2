from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Literal
from zoneinfo import ZoneInfo

from backend.common.timeutils import UTC, ensure_aware_utc

TimeframeUnit = Literal["s", "m", "h", "d"]


@dataclass(frozen=True, slots=True)
class Timeframe:
    """
    Candle timeframe definition.

    Canonical string representations match the existing DB-style format:
      - seconds: '1s','5s','15s','30s'
      - minutes: '1m','2m','3m','5m','15m','30m'
      - hours:   '1h','4h'
      - day:     '1d'   (accepts '1D' as input alias)
    """

    unit: TimeframeUnit
    step: int
    text: str

    @property
    def is_intraday(self) -> bool:
        return self.unit in {"s", "m", "h"}

    def as_timedelta_local(self) -> timedelta:
        if self.unit == "s":
            return timedelta(seconds=self.step)
        if self.unit == "m":
            return timedelta(minutes=self.step)
        if self.unit == "h":
            return timedelta(hours=self.step)
        if self.unit == "d":
            return timedelta(days=self.step)
        raise ValueError(f"unsupported unit: {self.unit}")


_TF_RE = re.compile(r"^\s*(\d+)?\s*([a-zA-Z]+)\s*$")


def parse_timeframe(value: str) -> Timeframe:
    """
    Parse timeframe strings like: '1s','5m','4h','1d'.
    Accepts TradingView-style 'D'/'1D' as aliases for '1d'.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timeframe must be a non-empty string")

    raw = value.strip()
    upper = raw.upper()
    if upper in {"D", "1D"}:
        unit, step = "d", 1
    else:
        m = _TF_RE.match(raw)
        if not m:
            raise ValueError(f"invalid timeframe: {value!r}")

        step_s, unit_s = m.group(1), m.group(2)
        step = int(step_s) if step_s is not None else 1
        unit_raw = unit_s.strip().lower()

        if unit_raw in {"s", "sec", "secs", "second", "seconds"}:
            unit = "s"
        elif unit_raw in {"m", "min", "mins", "minute", "minutes"}:
            unit = "m"
        elif unit_raw in {"h", "hr", "hrs", "hour", "hours"}:
            unit = "h"
        elif unit_raw in {"d", "day", "days"}:
            unit = "d"
        else:
            raise ValueError(f"invalid timeframe unit: {value!r}")

    text = f"{step}{unit}"
    tf = Timeframe(unit=unit, step=step, text=text)
    validate_timeframe(tf)
    return tf


def validate_timeframe(tf: Timeframe) -> None:
    allowed: dict[str, set[int]] = {
        "s": {1, 5, 15, 30},
        "m": {1, 2, 3, 5, 15, 30},
        "h": {1, 4},
        "d": {1},
    }
    if tf.unit not in allowed or tf.step not in allowed[tf.unit]:
        raise ValueError(f"unsupported timeframe: {tf.text}")


def parse_timeframes(values: Iterable[str]) -> list[Timeframe]:
    return [parse_timeframe(v) for v in values]


SUPPORTED_TIMEFRAMES: tuple[str, ...] = (
    "1s",
    "5s",
    "15s",
    "30s",
    "1m",
    "2m",
    "3m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "1d",
)


def floor_time(ts: datetime, timeframe: str | Timeframe, tz: str = "America/New_York") -> datetime:
    """
    Floor `ts` into a bar start aligned to wall-clock boundaries in `tz`.

    Returns a tz-aware UTC datetime.
    """
    ts_utc = ensure_aware_utc(ts)
    tf = parse_timeframe(timeframe) if isinstance(timeframe, str) else timeframe

    tzinfo = ZoneInfo(tz)
    local = ts_utc.astimezone(tzinfo)

    if tf.unit == "s":
        sec = (local.second // tf.step) * tf.step
        start_local = local.replace(second=sec, microsecond=0)
    elif tf.unit == "m":
        minute = (local.minute // tf.step) * tf.step
        start_local = local.replace(minute=minute, second=0, microsecond=0)
    elif tf.unit == "h":
        hour = (local.hour // tf.step) * tf.step
        start_local = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    elif tf.unit == "d":
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # pragma: no cover
        raise ValueError(f"unsupported unit: {tf.unit}")

    return start_local.astimezone(UTC)


def bar_range_utc(
    ts: datetime,
    timeframe: str | Timeframe,
    *,
    tz: str = "America/New_York",
    session_daily: bool = False,
) -> tuple[datetime, datetime]:
    """
    Return (bar_start_utc, bar_end_utc) for the bar containing `ts`.

    - Intraday: aligned to wall-clock boundaries in `tz` (TradingView-style).
    - Daily:
      - default: local midnight-to-midnight in `tz`
      - session_daily=True: local 09:30-to-09:30 "session day" in `tz`
    """
    ts_utc = ensure_aware_utc(ts)
    tf = parse_timeframe(timeframe) if isinstance(timeframe, str) else timeframe
    tzinfo = ZoneInfo(tz)

    if tf.unit != "d":
        start_utc = floor_time(ts_utc, tf, tz=tz)
        start_local = start_utc.astimezone(tzinfo)
        end_local = start_local + tf.as_timedelta_local()
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    # Daily: optionally align to RTH session start.
    local = ts_utc.astimezone(tzinfo)
    if session_daily:
        session_start = local.replace(hour=9, minute=30, second=0, microsecond=0)
        if local < session_start:
            prev = local - timedelta(days=1)
            session_start = prev.replace(hour=9, minute=30, second=0, microsecond=0)
        start_local = session_start
        end_local = (start_local + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)

