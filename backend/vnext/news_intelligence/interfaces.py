from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Sequence


class NewsConfidence(str, Enum):
    """
    Coarse confidence level for a derived `NewsEvent`.

    Notes:
    - This is *not* a trading signal. It is only a quality indicator for downstream
      analysis and human review.
    - If you need a numeric score, use `NewsEvent.confidence_score` (0.0-1.0).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class NewsItem:
    """
    A single licensed news artifact (article, press release, bulletin).

    Governance:
    - Must come from an approved, licensed source (see README).
    - Must not be scraped from the public web.
    """

    source: str
    published_at_utc: datetime
    headline: str

    # Optional metadata (recommended for traceability).
    id: str | None = None
    url: str | None = None
    summary: str | None = None
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NewsEvent:
    """
    A normalized, analysis-friendly event derived from one or more `NewsItem`s.

    This is intended for *intelligence* and feature extraction, not execution.
    Implementations should retain traceability via `source_items`.
    """

    ts_utc: datetime
    symbol: str
    event_type: str
    confidence: NewsConfidence

    # Optional fields.
    confidence_score: float | None = None  # expected range: 0.0 - 1.0
    rationale: str | None = None
    source_items: tuple[NewsItem, ...] = ()


class NewsIntelligenceProvider(ABC):
    """
    Read-only interface for fetching recent *licensed* news items.

    Non-operational contract:
    - This interface does not define ingestion, storage, or scraping behavior.
    - Implementations MUST adhere to `backend/vnext/news_intelligence/README.md`.
    - Returned results must never be used as direct trade triggers.
    """

    @abstractmethod
    def get_recent_news(self, symbol: str, lookback_minutes: int) -> Sequence[NewsItem]:
        """
        Return recent news items for `symbol` within `lookback_minutes`.

        Requirements:
        - Most recent items should be returned first (descending by published time).
        - Implementations should be deterministic for a fixed backing dataset.
        """

        raise NotImplementedError

