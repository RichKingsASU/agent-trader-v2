"""
Backward-compatible shim for candle timeframe utilities.

New code should prefer `backend.marketdata.candles.timeframe`.
"""

from __future__ import annotations

from backend.marketdata.candles.timeframe import (  # noqa: F401
    SUPPORTED_TIMEFRAMES,
    Timeframe,
    bar_range_utc,
    floor_time,
    parse_timeframe,
    parse_timeframes,
)

# Historical name used by some callers.
bucket_range_utc = bar_range_utc

__all__ = [
    "SUPPORTED_TIMEFRAMES",
    "Timeframe",
    "bar_range_utc",
    "bucket_range_utc",
    "floor_time",
    "parse_timeframe",
    "parse_timeframes",
]

