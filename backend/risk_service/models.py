from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from decimal import Decimal


class TradeCheckRequest(BaseModel):
    # Correlation across signal -> allocation -> execution (optional, but preserved when present)
    correlation_id: Optional[str] = None
    signal_id: Optional[str] = None
    allocation_id: Optional[str] = None
    execution_id: Optional[str] = None

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
    allowed: bool
    reason: Optional[str] = None
    scope: Optional[str] = None  # "account" or "strategy"
