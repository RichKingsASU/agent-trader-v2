from __future__ import annotations

"""
Fill/ledger models used by execution modules.

This file intentionally contains *no* broker integrations and is safe to import
in any runtime.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict
from pydantic.functional_validators import model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


OptionSide = Literal["BUY", "SELL"]


class OptionOrderIntent(BaseModel):
    """
    Validated option execution intent (already sized).

    Note: this is a *simulation* intent for shadow execution; it does not imply
    broker submission.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Identity / routing
    tenant_id: str = Field(..., min_length=1)
    uid: str = Field(..., min_length=1)
    strategy_id: Optional[str] = Field(default=None)

    correlation_id: str = Field(..., min_length=1)
    execution_id: Optional[str] = Field(default=None)
    idempotency_key: Optional[str] = Field(default=None)

    # Instrument
    symbol: str = Field(..., min_length=1, description="Underlying symbol (e.g., SPY)")
    option_symbol: str = Field(..., min_length=1, description="Provider/OPRA option contract symbol")

    # Order
    side: OptionSide
    quantity: int = Field(..., gt=0)

    # Pricing inputs (mid required; can be derived from bid/ask)
    mid_price: Optional[float] = Field(default=None, gt=0)
    bid_price: Optional[float] = Field(default=None, gt=0)
    ask_price: Optional[float] = Field(default=None, gt=0)

    # Metadata / audit
    created_at_utc: datetime = Field(default_factory=utc_now)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _ensure_mid(self) -> "OptionOrderIntent":
        if self.mid_price is not None:
            return self
        if self.bid_price is not None and self.ask_price is not None and self.ask_price >= self.bid_price:
            mid = (float(self.bid_price) + float(self.ask_price)) / 2.0
            return self.model_copy(update={"mid_price": mid})
        raise ValueError("mid_price is required (or provide bid_price and ask_price)")


class ShadowExecutionAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: Literal["execution.attempt"] = "execution.attempt"
    mode: Literal["shadow"] = "shadow"
    timestamp_utc: datetime = Field(default_factory=utc_now)

    correlation_id: Optional[str] = None
    execution_id: Optional[str] = None
    tenant_id: Optional[str] = None
    uid: Optional[str] = None

    instrument_type: Literal["option"] = "option"
    symbol: Optional[str] = None
    option_symbol: Optional[str] = None
    side: Optional[OptionSide] = None
    quantity: Optional[int] = None


class ShadowExecutionCompleted(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: Literal["execution.completed"] = "execution.completed"
    mode: Literal["shadow"] = "shadow"
    timestamp_utc: datetime = Field(default_factory=utc_now)

    correlation_id: Optional[str] = None
    execution_id: Optional[str] = None
    tenant_id: Optional[str] = None
    uid: Optional[str] = None

    instrument_type: Literal["option"] = "option"
    symbol: Optional[str] = None
    option_symbol: Optional[str] = None
    side: Optional[OptionSide] = None
    quantity: Optional[int] = None

    trade_id: Optional[str] = None
    position_id: Optional[str] = None
    fill_price: Optional[float] = None
    slippage_abs: Optional[float] = None


class ShadowOptionTrade(BaseModel):
    """
    A synthetic (shadow) option trade record.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    trade_id: str = Field(default_factory=lambda: str(uuid4()))

    tenant_id: str
    uid: str
    correlation_id: str
    execution_id: Optional[str] = None
    idempotency_key: Optional[str] = None

    symbol: str
    option_symbol: str
    side: OptionSide
    quantity: int

    mid_price: float
    slippage_abs: float
    fill_price: float
    filled_at_utc: datetime = Field(default_factory=utc_now)

    # State linkage
    position_id: str
    position_key: str

    # Risk / audit linkage (opaque; caller-provided IDs)
    risk_decision_id: Optional[str] = None
    risk_proposal_id: Optional[str] = None

    # Emitted artifacts
    execution_attempt: ShadowExecutionAttempt
    execution_completed: ShadowExecutionCompleted


class ShadowOptionPosition(BaseModel):
    """
    Shadow option position state (net, signed quantity).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    position_id: str
    position_key: str

    tenant_id: str
    uid: str
    symbol: str
    option_symbol: str

    # Signed quantity: BUY increments, SELL decrements.
    quantity: int
    entry_price: float

    opened_at_utc: datetime
    updated_at_utc: datetime

