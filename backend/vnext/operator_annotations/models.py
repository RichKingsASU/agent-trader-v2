from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnnotationScope(str, Enum):
    """
    Scope for an operator annotation / override.

    - GLOBAL: applies across the whole system
    - STRATEGY: applies to a named strategy
    - SYMBOL: applies to a specific tradable symbol
    """

    GLOBAL = "GLOBAL"
    STRATEGY = "STRATEGY"
    SYMBOL = "SYMBOL"


class OverrideReason(str, Enum):
    """
    Human-friendly categorization for why an operator action exists.

    Notes:
    - These values are intended to be auditable/stable.
    - If you need additional specificity, use `reason_detail` and/or `metadata`.
    """

    SAFETY = "SAFETY"
    COMPLIANCE = "COMPLIANCE"
    INCIDENT = "INCIDENT"
    OPERATIONS = "OPERATIONS"
    MARKET_CONDITION = "MARKET_CONDITION"
    EXPERIMENT = "EXPERIMENT"
    OTHER = "OTHER"


class OperatorNote(BaseModel):
    """
    Audit-friendly operator note / override record.

    This is a non-executing data model. Consumers MAY treat notes as advisory,
    unless `enforced=True` is explicitly honored by that consumer's policy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    note_id: UUID = Field(default_factory=uuid4, description="Stable unique identifier")
    created_at_utc: datetime = Field(default_factory=utc_now, description="UTC timestamp")

    created_by: str = Field(..., min_length=1, description="Human/operator identity")
    message: str = Field(..., min_length=1, description="Human-readable note")
    reason: OverrideReason = Field(default=OverrideReason.OTHER)
    reason_detail: Optional[str] = Field(
        default=None, description="Optional free-form details (ticket, incident id, etc.)"
    )

    scope: AnnotationScope = Field(default=AnnotationScope.GLOBAL)
    strategy_name: Optional[str] = Field(
        default=None, description="Required when scope=STRATEGY"
    )
    symbol: Optional[str] = Field(default=None, description="Required when scope=SYMBOL")

    enforced: bool = Field(
        default=False,
        description="Advisory unless a consumer explicitly enforces it",
    )
    expires_at_utc: Optional[datetime] = Field(
        default=None, description="Optional expiration (UTC)"
    )

    # Free-form structured payload for future use (feature-flags, thresholds, etc.)
    metadata: dict[str, Any] = Field(default_factory=dict)

