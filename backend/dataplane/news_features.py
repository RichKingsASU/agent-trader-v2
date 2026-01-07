from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Sequence

from backend.common.timeutils import ensure_aware_utc, parse_timestamp, utc_now

from .interfaces import NewsFeaturesProvider


def _freeze(obj: Any) -> Any:
    """
    Recursively freeze JSON-ish objects into immutable structures.

    - dict-like -> MappingProxyType(dict(...))
    - list/tuple/set -> tuple(...)
    - other scalars -> unchanged
    """

    if isinstance(obj, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple, set)):
        return tuple(_freeze(v) for v in obj)
    return obj


def _extract_ts(row: Mapping[str, Any]) -> datetime:
    """
    Best-effort timestamp extraction used by the in-memory mock.
    Accepts common keys: ts, timestamp, event_ts, created_at_utc.
    """

    for k in ("ts", "timestamp", "event_ts", "created_at_utc"):
        if k in row and row.get(k) is not None:
            return ensure_aware_utc(parse_timestamp(row.get(k)))
    raise ValueError("news feature row missing timestamp (expected ts|timestamp|event_ts|created_at_utc)")


@dataclass(frozen=True)
class InMemoryNewsFeaturesProvider(NewsFeaturesProvider):
    """
    Deterministic, read-only news-features provider for backtests.

    Notes:
    - This is intentionally *in-memory* and does not do any I/O.
    - Returned rows are deep-frozen (immutable) to enforce "read-only" behavior.
    - Rows are filtered by lookback against `now_fn()` and returned newest-first.
    """

    rows: Sequence[Mapping[str, Any]] = ()
    now_fn: Callable[[], datetime] = utc_now

    def get_recent_news_features(self, symbol: str, lookback_minutes: int) -> Sequence[Mapping[str, Any]]:
        sym = (symbol or "").strip().upper()
        if not sym or lookback_minutes <= 0:
            return ()

        now = ensure_aware_utc(self.now_fn())
        cutoff = now - timedelta(minutes=int(lookback_minutes))

        matched: list[Mapping[str, Any]] = []
        for r in self.rows:
            try:
                r_sym = str(r.get("symbol", "")).strip().upper()
            except Exception:
                continue
            if r_sym != sym:
                continue
            try:
                ts = _extract_ts(r)
            except Exception:
                continue
            if ts < cutoff:
                continue
            matched.append(r)

        matched.sort(key=_extract_ts, reverse=True)
        return tuple(_freeze(dict(m)) for m in matched)

