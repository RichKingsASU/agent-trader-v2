from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")
if _PYDANTIC_V2:  # pragma: no cover
    from pydantic import ConfigDict  # type: ignore[attr-defined]


SCHEMA_VERSION_V1: str = "1.0"


class _BaseSchema(BaseModel):
    """
    Shared schema behavior.

    Notes:
    - `extra=allow` so consumers can be forward-compatible with MINOR additions.
    - Producers should still construct narratives using these models to avoid typos.
    """

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="allow")
    else:  # pragma: no cover
        class Config:
            extra = "allow"


class EvidenceRef(_BaseSchema):
    """
    Lightweight pointer to an evidence artifact.

    This is intentionally storage-agnostic: it can point to a Firestore doc path,
    a blob URI, a local artifact path, or an internal identifier.
    """

    ref_type: str = Field(
        ...,
        description="Kind of reference: e.g. firestore_path, gcs_uri, file_path, url, internal_id.",
    )
    ref: str = Field(..., description="Reference value (opaque to this schema).")
    description: Optional[str] = Field(default=None, description="Human-friendly description.")


class ContributingFactor(_BaseSchema):
    """
    A single factor that contributed to the decision.
    """

    name: str = Field(..., description="Short name for the factor (stable identifier).")
    summary: str = Field(..., description="One-sentence explanation of how it affected the decision.")

    direction: Optional[Literal["supporting", "opposing", "neutral"]] = Field(
        default=None, description="Whether the factor supports or opposes the decision."
    )
    weight: Optional[float] = Field(
        default=None,
        description="Relative importance (0..1 recommended). Interpretation is model-defined.",
    )

    evidence: List[EvidenceRef] = Field(default_factory=list)
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional structured values supporting this factor (signals, metrics, thresholds).",
    )


class ContributingFactors(_BaseSchema):
    """
    Container for decision drivers and exclusions.
    """

    factors: List[ContributingFactor] = Field(default_factory=list)
    excluded: List[str] = Field(
        default_factory=list,
        description="Factors considered but excluded (e.g., stale inputs, insufficient evidence).",
    )
    notes: Optional[str] = Field(default=None, description="Optional global notes about factor handling.")


class ConfidenceStatement(_BaseSchema):
    """
    Human-readable + machine-usable confidence.

    The goal is to avoid hiding uncertainty: confidence must be explicit, bounded,
    and accompanied by rationale and known limitations.
    """

    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence in the decision (0..1).")
    level: Optional[Literal["low", "medium", "high"]] = Field(
        default=None, description="Optional bucketed label for the confidence value."
    )
    rationale: str = Field(..., description="Short explanation of why confidence is at this level.")

    calibration: Optional[str] = Field(
        default=None,
        description="Optional note on calibration/meaning of the confidence value (method-specific).",
    )
    limitations: List[str] = Field(
        default_factory=list, description="Known limitations/uncertainties that reduce reliability."
    )
    data_quality: Optional[str] = Field(
        default=None, description="Optional description of data freshness/coverage issues."
    )


class DecisionNarrative(_BaseSchema):
    """
    Canonical narrative explanation for a single decision.

    This is a schema-only artifact: it can be created deterministically, optionally augmented by an LLM,
    and then stored/audited/promoted downstream.
    """

    schema: Literal["decision_narrative"] = "decision_narrative"
    schema_version: Literal["1.0"] = SCHEMA_VERSION_V1

    decision_id: str = Field(..., description="Stable identifier of the decision being explained.")
    decision_type: Optional[str] = Field(
        default=None, description="Type/category of the decision (e.g., rebalance, risk_gate, proposal)."
    )
    decision_ts: datetime = Field(default_factory=_utcnow, description="Timestamp for the decision (UTC).")

    title: str = Field(..., description="Short headline describing what was decided.")
    summary: str = Field(..., description="1–3 sentence explanation of the decision and intent.")

    contributing_factors: ContributingFactors = Field(default_factory=ContributingFactors)
    confidence: ConfidenceStatement = Field(..., description="Bounded confidence + limitations.")

    assumptions: List[str] = Field(
        default_factory=list, description="Explicit assumptions required for this decision to be valid."
    )
    constraints: List[str] = Field(
        default_factory=list, description="Constraints that shaped the decision (risk limits, policy rules)."
    )
    warnings: List[str] = Field(
        default_factory=list, description="Safety/ops warnings to surface to humans."
    )

    alternatives: List[str] = Field(
        default_factory=list,
        description="Alternative actions considered (human-readable).",
    )
    counterfactuals: List[str] = Field(
        default_factory=list,
        description="If/then statements explaining how the decision might change under different conditions.",
    )

    evidence: List[EvidenceRef] = Field(
        default_factory=list,
        description="Global evidence references relevant to the decision (beyond per-factor evidence).",
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Optional metadata (versions, run ids, provenance) for audit/debug.",
    )

