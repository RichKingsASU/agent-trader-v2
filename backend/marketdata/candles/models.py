from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from backend.time.nyse_time import ensure_aware_utc


@dataclass(frozen=True, slots=True)
class Tick:
    """
    Minimal tick/trade model used for candle aggregation.
    """

    ts: datetime
    price: float
    size: int
    symbol: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ts", ensure_aware_utc(self.ts))
        object.__setattr__(self, "price", float(self.price))
        object.__setattr__(self, "size", int(self.size))
        sym = str(self.symbol).strip().upper()
        if not sym:
            raise ValueError("Tick.symbol must be non-empty")
        object.__setattr__(self, "symbol", sym)
        if self.size < 0:
            raise ValueError("Tick.size must be >= 0")


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: str
    start_ts: datetime
    end_ts: datetime

    open: float
    high: float
    low: float
    close: float
    volume: int

    vwap: float | None = None
    trade_count: int = 0
    is_final: bool = False

    def __post_init__(self) -> None:
        sym = str(self.symbol).strip().upper()
        if not sym:
            raise ValueError("Candle.symbol must be non-empty")
        object.__setattr__(self, "symbol", sym)
        object.__setattr__(self, "start_ts", ensure_aware_utc(self.start_ts))
        object.__setattr__(self, "end_ts", ensure_aware_utc(self.end_ts))
        object.__setattr__(self, "open", float(self.open))
        object.__setattr__(self, "high", float(self.high))
        object.__setattr__(self, "low", float(self.low))
        object.__setattr__(self, "close", float(self.close))
        object.__setattr__(self, "volume", int(self.volume))
        object.__setattr__(self, "trade_count", int(self.trade_count))
        object.__setattr__(self, "is_final", bool(self.is_final))
        if self.vwap is not None:
            object.__setattr__(self, "vwap", float(self.vwap))

    def to_row(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "ts_start": self.start_ts,
            "ts_end": self.end_ts,
            "open": float(self.open),
            "high": float(self.high),
            "low": float(self.low),
            "close": float(self.close),
            "volume": int(self.volume),
            "vwap": None if self.vwap is None else float(self.vwap),
            "trade_count": int(self.trade_count),
            "is_final": bool(self.is_final),
        }


# Back-compat alias for older codepaths/tests.
EmittedCandle = Candle

