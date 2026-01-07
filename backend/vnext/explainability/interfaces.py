"""
vNEXT Explainability — Narrative Interfaces (Governance-first)

Explainability is a mandatory artifact for any decision that is eligible for
promotion beyond observation-only workflows.

Constraints (see `backend/vnext/GOVERNANCE.md`):
- Contracts only: this module defines data models and interfaces, not logic.
- Deterministic preferred: narratives should be reproducible from logged inputs.
- LLM optional: generative embellishment is allowed only as a supplement and
  must never be the sole source of truth for the explanation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


SCHEMA_VERSION_V1: str = "1.0"


class ConfidenceLevel(str, Enum):
    """
    Coarse confidence level for human readability.

    This is intentionally decoupled from any numeric score to keep the schema
    usable even when calibration is not available.
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class ContributingFactor:
    """
    One factor that contributed to the decision.

    Notes:
    - `weight` is optional and has no mandated scale (teams may use [0,1] or
      normalized weights). It exists to support deterministic ranking.
    - `evidence` should reference concrete, logged inputs (features, prices,
      news ids, metrics, risk gates, etc.).
    """

    factor_id: str
    title: str
    detail: str

    # Optional signed direction hint for the factor's influence.
    # Examples: "supporting", "opposing", "neutral"
    direction: str = "supporting"

    # Optional strength/importance measure (implementation-defined).
    weight: float | None = None

    # Structured, auditable evidence for traceability.
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ContributingFactors:
    """
    Collection of factors for the decision narrative.

    This wrapper exists so producers can add deterministic ordering and
    extraction notes without changing the top-level `DecisionNarrative` shape.
    """

    factors: tuple[ContributingFactor, ...] = ()

    # Producer notes describing how factors were derived (deterministic method,
    # feature set, ranking approach, etc.). Keep this non-sensitive.
    methodology: str | None = None

    # Optional structured metadata for auditing (e.g., feature set version).
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConfidenceStatement:
    """
    Human-readable confidence statement for the decision.

    Notes:
    - `score` is optional. If used, it should be in [0, 1].
    - Producers should surface uncertainty honestly; low confidence is a valid
      outcome and must not be hidden.
    """

    level: ConfidenceLevel
    statement: str

    score: float | None = None

    # Concrete reasons for uncertainty (stale inputs, conflicting signals, etc.).
    uncertainties: tuple[str, ...] = ()

    # Optional calibration/tracking metadata (backtest window, model version, etc.).
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionNarrative:
    """
    Narrative explanation for a single decision.

    This is an auditable, portable, data-only artifact intended to be stored
    alongside the decision record.
    """

    schema_version: str
    decision_id: str

    # When the narrative was produced (recommended: UTC).
    generated_at: datetime

    # One-paragraph summary suitable for human review.
    summary: str

    contributing_factors: ContributingFactors
    confidence: ConfidenceStatement

    # Optional caveats/limitations that reviewers should consider.
    caveats: tuple[str, ...] = ()

    # Optional structured linkage back to inputs/trace ids (data-only).
    references: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class DecisionExplainer(Protocol):
    """
    Provider interface for decision explainability.

    Implementations SHOULD be deterministic given persisted inputs and should
    avoid network calls or hidden state. Any I/O must be injected and mockable.
    """

    def explain_decision(self, decision_id: str) -> DecisionNarrative:
        """Return a narrative explanation for the decision."""


def explain_decision(decision_id: str) -> DecisionNarrative:
    """
    Contract-only entrypoint for explainability.

    This function is intentionally not implemented in vNEXT contracts. Concrete
    implementations should live in a separate module/service that can:
    - read persisted decision inputs
    - compute deterministic factor attribution
    - optionally enhance prose with an LLM (never as the sole source of truth)
    """

    raise NotImplementedError(
        "Explainability is a contract in vNEXT. Provide an implementation of "
        "`DecisionExplainer.explain_decision(decision_id)` in a concrete module."
    )


def normalize_contributing_factors(
    factors: Sequence[ContributingFactor],
    *,
    max_factors: int | None = None,
) -> ContributingFactors:
    """
    Helper to produce a deterministic `ContributingFactors` object.

    Ordering rule:
    - If weights exist, sort by descending weight (None weights last).
    - Otherwise preserve the provided order.
    """

    fs = list(factors)

    if any(f.weight is not None for f in fs):
        fs.sort(
            key=lambda f: (
                f.weight is None,
                -(float(f.weight) if f.weight is not None else 0.0),
                f.factor_id,
            )
        )

    if max_factors is not None and max_factors >= 0:
        fs = fs[:max_factors]

    return ContributingFactors(factors=tuple(fs))

