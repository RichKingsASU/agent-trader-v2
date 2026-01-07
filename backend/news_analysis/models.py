from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional


class EventType(str, Enum):
    EARNINGS = "earnings"
    GUIDANCE = "guidance"
    MERGER_ACQUISITION = "merger_acquisition"
    REGULATORY = "regulatory"
    LITIGATION = "litigation"
    ANALYST_RATING = "analyst_rating"
    PRODUCT = "product"
    MACRO = "macro"
    INSIDER = "insider"
    OTHER = "other"


@dataclass(frozen=True)
class NewsFeatureRecord:
    """
    A minimal, storage-friendly feature record derived from a single news item.

    This is designed to be safe to persist and query, without embedding any
    non-deterministic or model-generated content.
    """

    feature_id: str
    symbol: str
    feature_name: str
    feature_value: float | str
    event_ts: Optional[datetime] = None
    source: Optional[str] = None
    headline: Optional[str] = None
    url: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "symbol": self.symbol,
            "feature_name": self.feature_name,
            "feature_value": self.feature_value,
            "event_ts": self.event_ts,
            "source": self.source,
            "headline": self.headline,
            "url": self.url,
            "metadata": self.metadata or {},
        }


def stable_feature_id(*parts: Any) -> str:
    """
    Deterministic id for idempotent storage.
    """
    s = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def get_text_fields(news: Mapping[str, Any]) -> tuple[str, str]:
    """
    Best-effort extraction for normalized news payloads.
    Returns (headline, body) as strings (possibly empty).
    """
    headline = str(news.get("headline") or news.get("title") or "")
    body = str(news.get("body") or news.get("summary") or "")
    return headline, body

