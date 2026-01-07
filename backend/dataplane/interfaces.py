from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence


class TickStore(ABC):
    """
    Storage abstraction for raw trades/ticks (append-only).

    Contract:
    - `ticks` are dict-like objects. Implementations should persist at least:
      - symbol (string)
      - timestamp / ts (datetime|str|epoch)
      - price (float)
      - size (int)
    """

    @abstractmethod
    def write_ticks(self, symbol: str, ticks: Sequence[Mapping[str, Any]]) -> None: ...

    @abstractmethod
    def query_ticks(self, symbol: str, start_utc: datetime, end_utc: datetime) -> list[dict[str, Any]]: ...


class CandleStore(ABC):
    """
    Storage abstraction for aggregated candles (append-only per partition, update-friendly later).

    Contract:
    - `candles` are dict-like objects or model-like objects with fields:
      - symbol, timeframe
      - ts_start_utc / ts_start, ts_end_utc / ts_end
      - open, high, low, close, volume
      - optional: vwap, trade_count, is_final
    """

    @abstractmethod
    def write_candles(self, symbol: str, timeframe: str, candles: Sequence[Any]) -> None: ...

    @abstractmethod
    def query_candles(
        self, symbol: str, timeframe: str, start_utc: datetime, end_utc: datetime
    ) -> list[dict[str, Any]]: ...


class ProposalStore(ABC):
    """
    Storage abstraction for strategy outputs (signals/proposals).

    Contract:
    - `proposals` can be dict-like or pydantic-like objects.
    - `query_proposals` should accept implementation-defined filters (scaffold).
    """

    @abstractmethod
    def write_proposals(self, proposals: Sequence[Any]) -> None: ...

    @abstractmethod
    def query_proposals(self, **filters: Any) -> list[dict[str, Any]]: ...

