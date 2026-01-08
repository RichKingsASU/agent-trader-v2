"""
Risk service contracts.

This module defines the typed request/response schemas used for risk checks.
All callers (strategy engine, strategy service, etc.) MUST use these models
instead of ad-hoc dict payloads to avoid implicit cross-service assumptions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel
from pydantic.config import ConfigDict


class TradeCheckRequest(BaseModel):
    """
    Request schema for POST /risk/check-trade.
    """

    model_config = ConfigDict(extra="forbid")

    broker_account_id: UUID
    strategy_id: Optional[UUID] = None
    symbol: str
    notional: Decimal
    side: str  # "buy" or "sell"
    current_open_positions: int
    current_trades_today: int
    current_day_loss: Decimal
    current_day_drawdown: Decimal


class RiskCheckResult(BaseModel):
    """
    Response schema for POST /risk/check-trade.
    """

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: Optional[str] = None
    scope: Optional[str] = None  # "account" or "strategy"

