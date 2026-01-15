from __future__ import annotations

"""
Alpaca quotes streamer (marketdata MCP server background task).

This module is intentionally import-safe:
- No env/secret access at import time
- No network calls at import time

The `marketdata-mcp-server` service imports `main()` as a background task.
In production, this should be replaced/extended with a real streaming client.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional


LAST_MARKETDATA_SOURCE: str = "alpaca_quotes_streamer"
_last_marketdata_ts: Optional[datetime] = None


def get_last_marketdata_ts() -> Optional[datetime]:
    return _last_marketdata_ts


async def main(ready_event: asyncio.Event | None = None) -> None:
    """
    Background task entrypoint.

    Current behavior:
    - Sets `ready_event` immediately (service readiness is handled by caller).
    - Updates an internal heartbeat timestamp periodically.

    NOTE: This is a placeholder implementation to keep service imports/test harnesses
    deterministic and non-networking by default.
    """
    global _last_marketdata_ts

    if ready_event is not None:
        try:
            ready_event.set()
        except Exception:
            pass

    while True:
        _last_marketdata_ts = datetime.now(timezone.utc)
        await asyncio.sleep(1.0)

