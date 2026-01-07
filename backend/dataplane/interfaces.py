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


class NewsFeaturesProvider(ABC):
    """
    Read-only interface for accessing *precomputed* news-derived features.

    Why this exists:
    - Strategies should remain deterministic and side-effect free.
    - Strategies must not perform network I/O to fetch news (backtests + sandbox).
    - Callers can inject a mock/snapshot provider for backtests.

    Contract:
    - Implementations must return a *read-only* sequence of mapping-like rows.
    - Rows should be ordered with the most-recent entries first (descending by timestamp).
    - The returned rows should be safe to cache and re-use by the caller.

    Expected row shape (recommended; not enforced):
      {
        "ts": <datetime|iso-str>,
        "symbol": <str>,
        "features": { ... numeric / categorical features ... },
        "source": <str|None>,
      }
    """

    @abstractmethod
    def get_recent_news_features(self, symbol: str, lookback_minutes: int) -> Sequence[Mapping[str, Any]]: ...

