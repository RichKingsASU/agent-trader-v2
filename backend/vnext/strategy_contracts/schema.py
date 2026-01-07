from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class StrategyCapabilities(str, Enum):
    """
    What a strategy is allowed to do (behavioral surface area).
    """

    # Safe-by-default, analysis-only outputs:
    OBSERVE = "OBSERVE"
    GENERATE_SIGNALS = "GENERATE_SIGNALS"
    GENERATE_TRADE_PROPOSALS = "GENERATE_TRADE_PROPOSALS"
    EMIT_ALERTS = "EMIT_ALERTS"

    # Higher-risk behaviors:
    EXECUTE_TRADES = "EXECUTE_TRADES"
    MODIFY_ORDERS = "MODIFY_ORDERS"


class RequiredFeatures(str, Enum):
    """
    Data/features a strategy consumes.

    Strategies must declare these explicitly; no implicit data consumption.
    """

    OHLCV = "OHLCV"
    QUOTES = "QUOTES"
    OPTIONS_CHAIN = "OPTIONS_CHAIN"
    OPTIONS_GREEKS = "OPTIONS_GREEKS"
    ORDER_FLOW = "ORDER_FLOW"
    GEX = "GEX"
    NEWS = "NEWS"
    SENTIMENT = "SENTIMENT"
    FUNDAMENTALS = "FUNDAMENTALS"
    MACRO = "MACRO"


class AllowedAgentModes(str, Enum):
    """
    Which global authority modes this strategy is permitted to run under.

    Note: HALTED is intentionally excluded from valid contracts (emergency stop).
    """

    DISABLED = "DISABLED"
    WARMUP = "WARMUP"
    LIVE = "LIVE"


class StrategyContract(BaseModel):
    """
    Schema-first declaration of a strategy's runtime surface area.

    This contract is validated before any promotion to higher privilege.
    """

    # Identity
    strategy_id: str = Field(..., description="Stable identifier (unique).")
    strategy_name: Optional[str] = Field(default=None, description="Human-friendly name.")

    # Declarations (MUST be explicit; empty list is allowed but field must exist)
    capabilities: list[StrategyCapabilities] = Field(
        ..., description="Explicitly declared capabilities.", min_length=0
    )
    required_features: list[RequiredFeatures] = Field(
        ..., description="Explicitly declared data/features consumed.", min_length=0
    )
    allowed_agent_modes: list[AllowedAgentModes] = Field(
        ..., description="Explicitly declared allowed global agent modes.", min_length=1
    )

    # Governance metadata
    declared_at_utc: Optional[datetime] = Field(default=None)
    owner: Optional[str] = Field(default=None)
    notes: Optional[str] = Field(default=None)

    @field_validator("strategy_id")
    @classmethod
    def _normalize_strategy_id(cls, v: str) -> str:
        sid = (v or "").strip()
        if not sid:
            raise ValueError("strategy_id is required")
        return sid

    @field_validator("capabilities", "required_features", "allowed_agent_modes")
    @classmethod
    def _dedupe_preserve_order(cls, v: list) -> list:
        # Preserve order while removing duplicates.
        seen = set()
        out = []
        for x in v or []:
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    @model_validator(mode="after")
    def _validate_cross_field_rules(self) -> "StrategyContract":
        # Fail-closed: strategies must explicitly declare data dependencies.
        if self.required_features is None:
            raise ValueError("required_features must be explicitly declared (use [] if none)")
        if self.capabilities is None:
            raise ValueError("capabilities must be explicitly declared (use [] if none)")

        # Execution capabilities imply LIVE is required.
        exec_caps = {StrategyCapabilities.EXECUTE_TRADES, StrategyCapabilities.MODIFY_ORDERS}
        if any(c in exec_caps for c in self.capabilities):
            if AllowedAgentModes.LIVE not in set(self.allowed_agent_modes):
                raise ValueError(
                    "execution capabilities require allowed_agent_modes to include LIVE"
                )

        return self

