from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from uuid import UUID

from pydantic import Field

from backend.contracts.v2.base import ContractBase, ContractFragment
from backend.contracts.v2.types import ExplanationSubjectType


class KeyFactor(ContractFragment):
    """
    A single factor used in a strategy explanation.
    """

    name: str = Field(min_length=1, max_length=128)
    value: Optional[str] = Field(default=None, max_length=512)
    weight: Optional[float] = Field(default=None, description="Optional relative importance score.")
    direction: Optional[str] = Field(
        default=None,
        max_length=16,
        description="Optional direction label (e.g., 'bullish', 'bearish', 'neutral').",
    )


class ModelInfo(ContractFragment):
    """
    Optional model/LLM metadata without vendor-specific fields.
    """

    model_name: Optional[str] = Field(default=None, max_length=128)
    model_version: Optional[str] = Field(default=None, max_length=64)
    prompt_hash: Optional[str] = Field(default=None, max_length=128, description="Optional stable prompt/template hash.")


class StrategyExplanation(ContractBase):
    """
    Human + machine-readable explanation for a strategy decision.
    """

    schema_name: Literal["agenttrader.v2.strategy_explanation"] = Field(..., alias="schema")

    explanation_id: UUID = Field(...)

    strategy_id: str = Field(min_length=1)
    subject_type: ExplanationSubjectType
    subject_id: UUID = Field(description="ID of the object being explained (e.g., signal_id, intent_id).")

    summary: str = Field(min_length=1, max_length=2048, description="Short summary suitable for dashboards.")
    narrative: Optional[str] = Field(default=None, max_length=16384, description="Optional longer narrative.")

    key_factors: Optional[tuple[KeyFactor, ...]] = Field(default=None)
    model_info: Optional[ModelInfo] = Field(default=None)

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional non-broker-specific explainability extensions (safe to share).",
    )

