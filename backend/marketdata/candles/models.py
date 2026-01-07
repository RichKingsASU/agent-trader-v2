from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.time.nyse_time import ensure_aware_utc


@dataclass(frozen=True, slots=True)
class EmittedCandle:
    symbol: str
    timeframe: str
    ts_start_utc: datetime
    ts_end_utc: datetime

    open: float
    high: float
    low: float
    close: float
    volume: int

    vwap: float | None = None
    trade_count: int | None = None
    is_final: bool = False

    # For observability / watermarking: the event timestamp that triggered this emission.
    source_event_ts: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts_start_utc", ensure_aware_utc(self.ts_start_utc))
        object.__setattr__(self, "ts_end_utc", ensure_aware_utc(self.ts_end_utc))
        if self.source_event_ts is not None:
            object.__setattr__(self, "source_event_ts", ensure_aware_utc(self.source_event_ts))

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "ts_start": self.ts_start_utc,
            "ts_end": self.ts_end_utc,
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": int(self.volume),
            "vwap": None if self.vwap is None else float(self.vwap),
            "trade_count": None if self.trade_count is None else int(self.trade_count),
            "is_final": bool(self.is_final),
        }

