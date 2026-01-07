from __future__ import annotations

"""
Schema-first contracts for strategy attribution & explainability.

Design goals:
- Explainability > optimization: output is built for humans, audits, and post-mortems
  (not for parameter tuning loops).
- Audit-first: schemas are strict; snapshots carry enough context to reproduce.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")
if _PYDANTIC_V2:  # pragma: no cover
    from pydantic import ConfigDict  # type: ignore[attr-defined]
    from pydantic import model_validator  # type: ignore[attr-defined]
else:  # pragma: no cover
    from pydantic import root_validator  # type: ignore[no-redef]


SCHEMA_VERSION_V1: str = "1.0"


class AttributionWindow(BaseModel):
    """
    Time window for attribution.

    Use UTC, and prefer [start, end) semantics for reproducible queries.
    """

    start_utc: datetime = Field(..., description="Window start in UTC.")
    end_utc: datetime = Field(..., description="Window end in UTC.")
    label: Optional[str] = Field(
        default=None,
        description="Optional human label, e.g. 'today', '1w', '2026-01'.",
    )

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid")

        @model_validator(mode="after")
        def _validate_range(self) -> "AttributionWindow":
            if self.end_utc <= self.start_utc:
                raise ValueError("end_utc must be > start_utc")
            return self
    else:  # pragma: no cover
        class Config:
            extra = "forbid"

        @root_validator
        def _validate_range(cls, values: dict[str, Any]) -> dict[str, Any]:
            s = values.get("start_utc")
            e = values.get("end_utc")
            if s is not None and e is not None and e <= s:
                raise ValueError("end_utc must be > start_utc")
            return values


class AttributionFactor(BaseModel):
    """
    One human-readable driver of performance for a given window.

    This is NOT a model parameter; it is an explanation artifact.
    """

    factor_id: str = Field(..., description="Stable machine identifier (snake_case).")
    label: str = Field(..., description="Short human label for UI/audit reports.")
    kind: Literal[
        "exposure",
        "selection",
        "timing",
        "execution",
        "risk",
        "carry",
        "regime",
        "other",
    ] = Field("other", description="Broad category for grouping/sorting.")

    contribution: float = Field(
        ...,
        description="Signed contribution for this window in the specified `unit`.",
    )
    unit: Literal["pnl_usd", "return_bps", "return_pct", "score"] = Field(
        "pnl_usd",
        description="Unit for `contribution` (schema-first; do not overload).",
    )

    direction: Optional[Literal["helped", "hurt", "mixed", "unknown"]] = Field(
        default=None,
        description="Human-friendly direction for narratives.",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional confidence in [0,1]. Prefer leaving None over guessing.",
    )

    description: Optional[str] = Field(
        default=None,
        description="One-paragraph explanation of why this factor mattered.",
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="Audit pointers (event ids, document ids, query hashes, etc.).",
    )
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic, JSON-serializable inputs used to compute this factor.",
    )

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid")
    else:  # pragma: no cover
        class Config:
            extra = "forbid"


class StrategyAttributionSnapshot(BaseModel):
    """
    A point-in-time, auditable explanation of a strategy's performance over a window.
    """

    schema: Literal["strategy_attribution_snapshot"] = "strategy_attribution_snapshot"
    schema_version: Literal["1.0"] = SCHEMA_VERSION_V1

    strategy_id: str = Field(..., description="Strategy identifier.")
    window: AttributionWindow = Field(..., description="Attribution window.")

    computed_at_utc: datetime = Field(
        default_factory=_utcnow,
        description="When this snapshot was computed (UTC).",
    )

    headline: Optional[str] = Field(
        default=None,
        description="Optional one-line summary for operators (e.g. 'mostly beta, poor fills').",
    )

    # Core, schema-first output.
    factors: list[AttributionFactor] = Field(
        default_factory=list,
        description="Ranked or grouped factors explaining performance.",
    )

    # Audit-first metadata for reproducibility (dataset versions, query params, etc.).
    audit: dict[str, Any] = Field(
        default_factory=dict,
        description="Deterministic metadata needed to reproduce the snapshot.",
    )

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="forbid")
    else:  # pragma: no cover
        class Config:
            extra = "forbid"


class StrategyAttributionProvider(ABC):
    """
    Storage/compute boundary for attribution.

    Implementations may:
    - read realized P&L / fills from the ledger
    - read signals/proposals, exposures, market regimes
    - compute a strict `StrategyAttributionSnapshot` suitable for audits
    """

    @abstractmethod
    def get_attribution(self, strategy_id: str, window: AttributionWindow) -> StrategyAttributionSnapshot: ...

