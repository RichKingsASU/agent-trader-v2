from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from uuid import UUID


class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    status: str = "draft"
    target_symbols: List[str] = ["SPY", "IWM"]
    instrument: str = "option"
    broker_account_id: UUID
    config: dict = {}
    trading_session: dict = {
        "timezone": "America/New_York",
        "market_hours_only": True,
        "session_start": "09:30",
        "session_end": "16:00",
    }


class Strategy(BaseModel):
    id: UUID
    uid: str
    name: str
    description: Optional[str]
    status: str
    target_symbols: List[str]
    instrument: str
    broker_account_id: UUID
    config: dict
    trading_session: dict


class PaperOrderCreate(BaseModel):
    uid: str
    broker_account_id: UUID
    strategy_id: UUID
    symbol: str
    instrument_type: str
    side: str
    order_type: str
    time_in_force: str = "day"
    notional: float
    quantity: Optional[float] = None
    risk_allowed: bool = True
    risk_scope: Optional[str] = None
    risk_reason: Optional[str] = None
    raw_order: Dict[str, Any]
    status: str = "simulated"


class PaperOrder(PaperOrderCreate):
    id: UUID
    created_at: str
