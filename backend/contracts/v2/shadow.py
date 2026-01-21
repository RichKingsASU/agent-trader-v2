from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from uuid import UUID

from pydantic import Field
from pydantic.types import AwareDatetime

from backend.contracts.v2.base import ContractBase
from backend.contracts.v2.types import AssetClass, DecimalString, Side


class ShadowTrade(ContractBase):
    """
    A broker-agnostic, non-executed (paper/shadow) trade used for attribution,
    monitoring, and shadow PnL pipelines.
    """

    schema_name: Literal["agenttrader.v2.shadow_trade"] = Field(..., alias="schema")

    shadow_trade_id: UUID = Field(...)

    strategy_id: Optional[str] = Field(default=None, min_length=1)
    intent_id: Optional[UUID] = Field(default=None, description="Optional linkage to an OrderIntent.")

    symbol: str = Field(min_length=1)
    asset_class: AssetClass = Field(...)
    side: Side

    quantity: DecimalString
    price: DecimalString

    traded_at: AwareDatetime = Field(..., description="UTC timestamp when recorded.")

    fees: Optional[DecimalString] = Field(default=None, description="Optional fees in quote currency.")
    notes: Optional[str] = Field(default=None, max_length=2048)

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional non-broker-specific extension point for shadow execution assumptions.",
    )

