from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from uuid import UUID

from pydantic import Field
from pydantic.types import AwareDatetime

from backend.contracts.v2.base import ContractBase, ContractFragment
from backend.contracts.v2.types import DecimalString, RiskDecisionType


class RiskReason(ContractFragment):
    code: str = Field(min_length=1, max_length=64, description="Stable machine-readable reason code.")
    message: Optional[str] = Field(default=None, max_length=512, description="Optional human-readable detail.")
    severity: Optional[str] = Field(
        default=None,
        max_length=32,
        description="Optional severity label (e.g., 'warn', 'error').",
    )


class RiskModification(ContractFragment):
    """
    Suggested modifications when decision=modify (e.g., reduce size).
    """

    quantity: Optional[DecimalString] = Field(default=None)
    notional: Optional[DecimalString] = Field(default=None)
    max_notional: Optional[DecimalString] = Field(default=None)
    max_slippage_bps: Optional[int] = Field(default=None, ge=0, le=10000)

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(default=None)


class RiskDecision(ContractBase):
    """
    Result of evaluating an OrderIntent (or related action) against risk policy.
    """

    schema_name: Literal["agenttrader.v2.risk_decision"] = Field(..., alias="schema")

    decision_id: UUID = Field(...)
    evaluated_at: AwareDatetime = Field(..., description="UTC evaluation timestamp.")

    # Linkage
    intent_id: Optional[UUID] = Field(default=None, description="Optional linkage to the evaluated OrderIntent.")
    strategy_id: Optional[str] = Field(default=None, min_length=1)
    account_id: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Optional tenant-level account/portfolio id (not broker account id).",
    )

    decision: RiskDecisionType
    allowed: bool = Field(
        description="Convenience boolean (typically decision==allow). Consumers should primarily use `decision`.",
    )

    reasons: tuple[RiskReason, ...] = Field(
        ...,
        description="Zero-or-more reasons. SHOULD be non-empty for deny/modify.",
    )
    modification: Optional[RiskModification] = Field(
        default=None,
        description="Present when decision=modify to describe suggested changes.",
    )

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional non-broker-specific policy evaluation details (redacted/approved for sharing).",
    )

