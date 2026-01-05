from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_PYDANTIC_V2 = hasattr(BaseModel, "model_validate")

if _PYDANTIC_V2:  # pragma: no cover
    from pydantic import ConfigDict  # type: ignore[attr-defined]


SCHEMA_VERSION_V1: str = "1.0"


class _BaseMessage(BaseModel):
    """
    Shared envelope fields.

    Notes:
    - `extra=allow` so consumers can be forward-compatible with MINOR additions.
    - Producers should still construct messages using these models to avoid typos.
    """

    tenant_id: str
    ts: datetime = Field(default_factory=_utcnow)

    if _PYDANTIC_V2:  # pragma: no cover
        model_config = ConfigDict(extra="allow")
    else:  # pragma: no cover
        class Config:
            extra = "allow"


class MarketEventV1(_BaseMessage):
    schema: Literal["market"] = "market"
    schema_version: Literal["1.0"] = SCHEMA_VERSION_V1

    symbol: str
    source: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class SignalEventV1(_BaseMessage):
    schema: Literal["signal"] = "signal"
    schema_version: Literal["1.0"] = SCHEMA_VERSION_V1

    strategy_id: str
    symbol: str

    signal_type: str
    confidence: Optional[float] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class OrderRequestV1(_BaseMessage):
    schema: Literal["order_request"] = "order_request"
    schema_version: Literal["1.0"] = SCHEMA_VERSION_V1

    account_id: str
    strategy_id: Optional[str] = None
    user_id: Optional[str] = None

    symbol: str
    instrument_type: Optional[str] = None
    side: Literal["buy", "sell"]

    order_type: str
    time_in_force: str = "day"

    notional: Optional[float] = None
    quantity: Optional[float] = None
    limit_price: Optional[float] = None

    # Broker/execution payload (or DB insertion payload for paper trading).
    raw_order: Dict[str, Any] = Field(default_factory=dict)

    meta: Dict[str, Any] = Field(default_factory=dict)


class FillEventV1(_BaseMessage):
    schema: Literal["fill"] = "fill"
    schema_version: Literal["1.0"] = SCHEMA_VERSION_V1

    account_id: str
    symbol: str

    order_id: Optional[str] = None
    fill_id: Optional[str] = None

    side: Optional[Literal["buy", "sell"]] = None
    quantity: float
    price: float

    data: Dict[str, Any] = Field(default_factory=dict)


class OpsEventV1(_BaseMessage):
    schema: Literal["ops"] = "ops"
    schema_version: Literal["1.0"] = SCHEMA_VERSION_V1

    service: str
    level: Literal["debug", "info", "warn", "error"] = "info"
    event: str
    message: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)

