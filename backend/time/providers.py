"""
Provider-specific timestamp normalization.

Goal: keep provider quirks out of the rest of the codebase.
All functions return tz-aware UTC datetimes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.time.nyse_time import parse_ts, to_utc


def normalize_alpaca_timestamp(x: Any) -> datetime:
    """
    Normalize common Alpaca timestamp shapes into tz-aware UTC.

    Alpaca shapes observed in this repo:
    - ISO8601 strings (often with trailing 'Z')
    - `datetime` (tz-aware or naive)
    - pandas.Timestamp (duck-typed via `parse_ts`)
    - epoch seconds/milliseconds (occasionally in custom payloads)
    """

    return parse_ts(x)


def normalize_tastytrade_timestamp(x: Any) -> datetime:
    """
    Normalize Tastytrade timestamps to tz-aware UTC.

    Stub: implement when/if a Tastytrade provider is wired in.
    """

    # Best-effort generic parse for now.
    if isinstance(x, datetime):
        return to_utc(x)
    return parse_ts(x)


__all__ = ["normalize_alpaca_timestamp", "normalize_tastytrade_timestamp"]

