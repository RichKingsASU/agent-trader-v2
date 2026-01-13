"""
Deprecated compatibility shim.

Prefer `backend.marketdata.candles.timeframe`.
"""

from __future__ import annotations

from datetime import datetime

from backend.marketdata.candles.timeframe import (  # noqa: F401
    SUPPORTED_TIMEFRAMES,
    Timeframe,
    bar_range_utc,
    floor_time,
    parse_timeframe,
    parse_timeframes,
)


def bucket_range_utc(
    ts_utc: datetime,
    tf: Timeframe,
    *,
    tz_market: str = "America/New_York",
    session_daily: bool = False,
) -> tuple[datetime, datetime]:
    """
    Back-compat alias for older codepaths.

    Equivalent to `bar_range_utc(ts_utc, tf, tz=tz_market, session_daily=session_daily)`.
    """

    return bar_range_utc(ts_utc, tf, tz=tz_market, session_daily=session_daily)

