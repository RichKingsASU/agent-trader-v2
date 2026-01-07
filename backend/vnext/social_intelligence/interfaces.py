from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Sequence


class SocialSource(str, Enum):
    """
    Allowed data sources for vNEXT social intelligence.

    Governance note:
    - This enum is intentionally narrow. Adding sources must be a deliberate, reviewed change.
    """

    DISCORD = "discord"
    REDDIT = "reddit"


@dataclass(frozen=True, slots=True)
class SocialMention:
    """
    A single *permissioned* social mention event.

    Governance constraints (non-exhaustive):
    - No crawling/scraping: this must be produced only via explicit APIs and/or bot permissions.
    - Data minimization: avoid storing raw content or direct identifiers unless strictly required.
    - Prefer irreversible identifiers (hashes) if correlation is needed.
    """

    symbol: str
    ts_utc: datetime
    source: SocialSource

    # Location context (permissioned Discord channel; Reddit subreddit/thread).
    context: str | None = None

    # Minimal content representation; implementations should avoid storing full text.
    content_hash: str | None = None
    text_excerpt: str | None = None

    # Optional author linkage for anti-spam / velocity dedupe; prefer hashed/opaque IDs.
    author_id_hash: str | None = None

    # Implementation-defined tags (e.g., "rumor", "earnings", "halt", "pump", "scam").
    tags: tuple[str, ...] = ()

    # Additional implementation-defined metadata (must remain non-sensitive).
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SocialVelocitySignal:
    """
    Aggregate velocity / acceleration of mentions for a symbol over a lookback window.

    This is a *feature* signal, not a trading directive.
    """

    symbol: str
    as_of_utc: datetime
    lookback_minutes: int

    mentions_count: int
    unique_authors_count: int | None = None

    # Derived metrics (optional; implementation dependent).
    mentions_per_minute: float | None = None
    zscore: float | None = None
    percent_change_vs_baseline: float | None = None

    # Free-form explanation suitable for audit logs.
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class CredibilityScore:
    """
    Credibility assessment for a set of social signals.

    Governance note:
    - Must be explainable and auditable.
    - Must not embed or leak sensitive user identifiers.
    - Should emphasize *uncertainty* and avoid overconfident scoring.
    """

    symbol: str
    as_of_utc: datetime

    # Normalized 0..1 score where higher means more credible.
    score: float

    # Human/audit-friendly rationale; keep short and structured.
    rationale: Sequence[str] = ()

    # Optional structured inputs for reproducibility (e.g., evidence counts, heuristics).
    inputs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SocialRiskAssessment:
    """
    Output of `get_social_risk(symbol)` for downstream risk-aware consumers.

    This is intentionally conservative: it is a read-only assessment snapshot and does not
    authorize any data collection or network access by itself.
    """

    symbol: str
    as_of_utc: datetime
    velocity: SocialVelocitySignal
    credibility: CredibilityScore

    # Optional minimal samples for debugging/audit; avoid raw text/PII.
    sample_mentions: Sequence[SocialMention] = ()

    # Implementation-defined risk label (e.g., "none|low|medium|high|critical|unknown").
    risk_band: str = "unknown"

    # Short governance/audit note (e.g., "discord-only", "reddit-api", "no raw content stored").
    governance_note: str | None = None


class SocialRiskProvider(ABC):
    """
    Read-only interface for social/community-derived *risk* awareness.

    Deferred-by-design:
    - This module defines contracts and governance constraints only.
    - Implementations must be explicitly approved and must comply with platform ToS,
      privacy requirements, and internal data-handling policies.
    """

    @abstractmethod
    def get_social_risk(self, symbol: str) -> SocialRiskAssessment:
        """
        Return a snapshot of social risk for `symbol`.

        Implementations must:
        - Use only permissioned sources (see README) and official APIs.
        - Avoid crawling/scraping.
        - Be deterministic given the same underlying event store snapshot.
        """

