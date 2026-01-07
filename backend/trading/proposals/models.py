from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProposalSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ProposalAssetType(str, Enum):
    OPTION = "OPTION"
    EQUITY = "EQUITY"
    FUTURE = "FUTURE"


class ProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ProposalTimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"


class OptionRight(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class ProposalOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expiration: date = Field(..., description="Option expiration date (YYYY-MM-DD)")
    right: OptionRight = Field(..., description="CALL|PUT")
    strike: float = Field(..., gt=0, description="Strike price")
    contract_symbol: Optional[str] = Field(
        default=None, description="Optional provider-specific contract symbol"
    )


class ProposalRationale(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    short_reason: str = Field(..., min_length=1, description="Short human-readable rationale")
    indicators: Dict[str, Any] = Field(
        default_factory=dict,
        description="Redacted-safe indicator snapshot (no secrets / API keys)",
    )


class ProposalRisk(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_loss_usd: Optional[float] = Field(default=None, gt=0)
    stop_loss: Optional[float] = Field(default=None, gt=0)
    take_profit: Optional[float] = Field(default=None, gt=0)


class ProposalConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid_until_utc: datetime = Field(..., description="UTC timestamp when proposal expires")
    requires_human_approval: bool = Field(
        default=True,
        description="Fail-safe guard: proposals default to requiring human approval",
    )


class OrderProposal(BaseModel):
    """
    Auditable, non-executing trade intent.

    This object is safe to emit from any strategy runtime. It MUST NOT be used
    as an execution instruction without additional authorization and review.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID = Field(default_factory=uuid4)
    created_at_utc: datetime = Field(default_factory=utc_now)

    repo_id: str
    agent_name: str
    strategy_name: str
    strategy_version: Optional[str] = None
    correlation_id: str

    symbol: str = Field(..., min_length=1, description="Underlying symbol (e.g., SPY)")
    asset_type: ProposalAssetType = Field(default=ProposalAssetType.OPTION)
    option: Optional[ProposalOption] = None

    side: ProposalSide
    quantity: int = Field(..., gt=0)
    limit_price: Optional[float] = Field(default=None, gt=0)
    time_in_force: ProposalTimeInForce = Field(default=ProposalTimeInForce.DAY)

    rationale: ProposalRationale
    risk: ProposalRisk = Field(default_factory=ProposalRisk)
    constraints: ProposalConstraints

    status: ProposalStatus = Field(default=ProposalStatus.PROPOSED)

