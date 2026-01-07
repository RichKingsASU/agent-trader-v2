from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True, slots=True)
class HeartbeatSnapshot:
    last_tick_utc: Optional[datetime]

    def last_tick_epoch_seconds(self) -> Optional[int]:
        if self.last_tick_utc is None:
            return None
        return int(self.last_tick_utc.replace(tzinfo=timezone.utc).timestamp())


_lock = threading.Lock()
_last_tick_utc: Optional[datetime] = None


def update_last_tick(ts_utc: Optional[datetime] = None) -> None:
    """
    Record the most recent marketdata tick time (UTC).

    Producer side should call this whenever it receives a live market data event.
    """
    global _last_tick_utc
    ts = ts_utc or datetime.now(timezone.utc)
    # Ensure aware UTC
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    with _lock:
        _last_tick_utc = ts


def snapshot() -> HeartbeatSnapshot:
    with _lock:
        ts = _last_tick_utc
    return HeartbeatSnapshot(last_tick_utc=ts)

