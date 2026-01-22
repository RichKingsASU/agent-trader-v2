from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping, Optional

OptionRight = Literal["call", "put"]


@dataclass(frozen=True)
class OptionContract:
    symbol: str
    underlying_symbol: str
    expiration_date: date
    strike: float
    right: OptionRight


@dataclass(frozen=True)
class QuoteMetrics:
    bid: Optional[float]
    ask: Optional[float]
    bid_size: Optional[float]
    ask_size: Optional[float]
    volume: Optional[float]
    open_interest: Optional[float]
    snapshot_time: Optional[str]

    @property
    def mid(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        if self.bid <= 0 or self.ask <= 0:
            return None
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> Optional[float]:
        if self.bid is None or self.ask is None:
            return None
        if self.bid <= 0 or self.ask <= 0:
            return None
        return self.ask - self.bid

    @property
    def rel_spread(self) -> Optional[float]:
        m = self.mid
        s = self.spread
        if m is None or s is None or m <= 0:
            return None
        return s / m

    @property
    def total_size(self) -> float:
        return float(self.bid_size or 0.0) + float(self.ask_size or 0.0)


@dataclass(frozen=True)
class SelectedOptionContract:
    contract_symbol: str
    underlying_symbol: str
    right: OptionRight
    strike: float
    expiration_date: date
    dte: int
    underlying_price: float
    quote: QuoteMetrics
    raw_snapshot: Optional[Mapping[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_symbol": self.contract_symbol,
            "underlying_symbol": self.underlying_symbol,
            "right": self.right,
            "strike": self.strike,
            "expiration_date": self.expiration_date.isoformat(),
            "dte": int(self.dte),
            "underlying_price": float(self.underlying_price),
            "bid": self.quote.bid,
            "ask": self.quote.ask,
            "mid": self.quote.mid,
            "spread": self.quote.spread,
            "rel_spread": self.quote.rel_spread,
            "bid_size": self.quote.bid_size,
            "ask_size": self.quote.ask_size,
            "total_size": self.quote.total_size,
            "volume": self.quote.volume,
            "open_interest": self.quote.open_interest,
            "snapshot_time": self.quote.snapshot_time,
        }


def parse_option_right(value: Any) -> OptionRight:
    s = "" if value is None else str(value).strip().lower()
    if s in {"call", "c"}:
        return "call"
    if s in {"put", "p"}:
        return "put"
    raise ValueError(f"Unsupported option right: {value!r}")


def as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}

