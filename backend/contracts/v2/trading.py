from __future__ import annotations

from typing import Any, Dict, Optional, Literal
from uuid import UUID

from pydantic import Field
from pydantic.types import AwareDatetime

from backend.contracts.v2.base import ContractBase, ContractFragment
from backend.contracts.v2.types import (
    AssetClass,
    CurrencyCode,
    DecimalString,
    OrderType,
    SignalAction,
    Side,
    TimeInForce,
)


class TradingSignal(ContractBase):
    """
    A broker-agnostic trading signal emitted by a strategy/agent.
    """

    schema_name: Literal["agenttrader.v2.trading_signal"] = Field(..., alias="schema")

    signal_id: UUID = Field(...)
    strategy_id: str = Field(min_length=1, description="Stable strategy identifier (string, not necessarily UUID).")

    symbol: str = Field(min_length=1)
    asset_class: AssetClass = Field(...)

    action: SignalAction
    side: Optional[Side] = Field(
        default=None,
        description="Optional explicit side. Some actions (e.g., exit/hold) may not map to buy/sell.",
    )

    generated_at: AwareDatetime = Field(..., description="UTC timestamp when computed.")
    expires_at: Optional[AwareDatetime] = Field(default=None, description="Optional UTC expiry timestamp.")

    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Optional confidence in [0,1].")
    strength: Optional[float] = Field(
        default=None,
        description="Optional unbounded signal strength score (strategy-defined).",
    )

    horizon: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional holding horizon label (e.g., 'intraday', 'swing').",
    )
    rationale: Optional[str] = Field(default=None, max_length=4096, description="Optional human-readable rationale.")

    # Optional, strategy-defined structured data. Keep broker-agnostic.
    features: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional strategy features/inputs snapshot (non-sensitive).",
    )

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional non-broker-specific extension point for strategy/agent options.",
    )


class OrderConstraints(ContractFragment):
    """
    Broker-agnostic constraints for executing an OrderIntent.
    """

    max_slippage_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    max_notional: Optional[DecimalString] = Field(default=None, description="Max notional (quote currency).")
    min_fill_quantity: Optional[DecimalString] = Field(default=None)
    allow_partial_fills: Optional[bool] = Field(default=None)

    # Optional `options` extension point.
    options: Optional[Dict[str, Any]] = Field(default=None)


class OrderIntent(ContractBase):
    """
    A normalized, broker-agnostic intent to place an order.

    This is the canonical object that downstream risk/execution services consume.
    """

    schema_name: Literal["agenttrader.v2.order_intent"] = Field(..., alias="schema")

    intent_id: UUID = Field(...)

    account_id: str = Field(
        min_length=1,
        description="Stable account/portfolio identifier within the tenant (not broker account id).",
    )
    strategy_id: Optional[str] = Field(default=None, min_length=1)
    signal_id: Optional[UUID] = Field(default=None, description="Optional linkage to a TradingSignal.")

    symbol: str = Field(min_length=1)
    asset_class: AssetClass = Field(...)

    side: Side
    order_type: OrderType
    time_in_force: TimeInForce

    # Exactly one of quantity or notional SHOULD be provided (not enforced in schema).
    quantity: Optional[DecimalString] = Field(default=None, description="Base quantity as decimal string.")
    notional: Optional[DecimalString] = Field(
        default=None,
        description="Quote-currency notional as decimal string.",
    )

    limit_price: Optional[DecimalString] = Field(default=None)
    stop_price: Optional[DecimalString] = Field(default=None)

    currency: Optional[CurrencyCode] = Field(default=None, description="Optional quote currency (ISO 4217).")

    client_intent_ref: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional idempotent client reference (stable across retries).",
    )

    constraints: Optional[OrderConstraints] = Field(default=None)

    # IMPORTANT: `options` is intentionally OPTIONAL (per requirements).
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional non-broker-specific execution/routing options.",
    )

