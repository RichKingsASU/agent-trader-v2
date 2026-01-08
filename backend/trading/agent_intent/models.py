from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class IntentSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    FLAT = "FLAT"


class IntentAssetType(str, Enum):
    OPTION = "OPTION"
    EQUITY = "EQUITY"
    FUTURE = "FUTURE"


class IntentKind(str, Enum):
    """
    High-level intent semantics.

    This is explicitly NOT an execution instruction; it is a request for the
    allocator to determine if/how to size and route.
    """

    DIRECTIONAL = "DIRECTIONAL"  # open/close directional exposure
    DELTA_HEDGE = "DELTA_HEDGE"  # reduce net delta toward a target
    EXIT = "EXIT"  # reduce/close exposure (allocator chooses mechanics)


class OptionRight(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class IntentOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expiration: date = Field(..., description="Option expiration date (YYYY-MM-DD)")
    right: OptionRight
    strike: float = Field(..., gt=0)
    contract_symbol: Optional[str] = None


class AgentIntentRationale(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    short_reason: str = Field(..., min_length=1)
    indicators: Dict[str, Any] = Field(default_factory=dict)


class AgentIntentConstraints(BaseModel):
    """
    Constraints are non-capital knobs: time, price, and safety flags.

    Capital and sizing are intentionally excluded. The allocator MAY use these
    constraints when determining an executable order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    valid_until_utc: datetime
    requires_human_approval: bool = True

    # Optional execution-shaping constraints (non-capital).
    order_type: str = Field(default="market", description='"market" | "limit" | ...')
    time_in_force: str = Field(default="day", description='"day" | "gtc" | ...')
    limit_price: Optional[float] = Field(default=None, gt=0)

    # Optional risk-shaping constraints that do not specify capital:
    # - For delta hedges, provide the observed net delta to neutralize.
    delta_to_hedge: Optional[float] = Field(
        default=None,
        description="Signed net delta to offset (allocator derives hedge quantity).",
    )


class AgentIntent(BaseModel):
    """
    Agent → allocator contract.

    Safety property: this message contains NO capital quantities (no notional,
    no qty). It is safe for agents/strategies to emit.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent_id: UUID = Field(default_factory=uuid4)
    created_at_utc: datetime = Field(default_factory=utc_now)

    repo_id: str
    agent_name: str
    strategy_name: str
    strategy_version: Optional[str] = None
    correlation_id: str

    symbol: str = Field(..., min_length=1)
    asset_type: IntentAssetType = Field(default=IntentAssetType.EQUITY)
    option: Optional[IntentOption] = None

    kind: IntentKind = Field(default=IntentKind.DIRECTIONAL)
    side: IntentSide
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    rationale: AgentIntentRationale
    constraints: AgentIntentConstraints

