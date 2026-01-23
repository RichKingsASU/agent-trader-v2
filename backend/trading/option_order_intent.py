from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import isfinite
from typing import Any, Mapping


class OptionType(str, Enum):
    """
    Listed option right (CALL/PUT).
    """

    CALL = "CALL"
    PUT = "PUT"


class OrderSide(str, Enum):
    """
    Trade direction (BUY/SELL).
    """

    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True, slots=True)
class OptionOrderIntent:
    """
    Pure data object representing an option order intent.

    Constraints:
    - No broker imports
    - No execution logic
    - Standard-library only
    """

    symbol: str
    option_type: OptionType | str
    strike: float
    expiry: date
    side: OrderSide | str
    quantity: int
    reason: str
    strategy_id: str

    def __post_init__(self) -> None:
        symbol = (self.symbol or "").strip().upper()
        if not symbol:
            raise ValueError("symbol must be a non-empty string")
        object.__setattr__(self, "symbol", symbol)

        # Normalize enums from strings (case-insensitive).
        option_type = self.option_type
        if isinstance(option_type, str):
            try:
                option_type = OptionType[option_type.strip().upper()]
            except KeyError as e:
                raise ValueError("option_type must be CALL or PUT") from e
        object.__setattr__(self, "option_type", option_type)

        side = self.side
        if isinstance(side, str):
            try:
                side = OrderSide[side.strip().upper()]
            except KeyError as e:
                raise ValueError("side must be BUY or SELL") from e
        object.__setattr__(self, "side", side)

        # Basic value checks.
        if not isinstance(self.expiry, date):
            raise TypeError("expiry must be a datetime.date")

        if not isfinite(float(self.strike)) or float(self.strike) <= 0:
            raise ValueError("strike must be a finite positive number")

        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool) or self.quantity <= 0:
            raise ValueError("quantity must be a positive integer")

        reason = (self.reason or "").strip()
        if not reason:
            raise ValueError("reason must be a non-empty string")
        object.__setattr__(self, "reason", reason)

        strategy_id = (self.strategy_id or "").strip()
        if not strategy_id:
            raise ValueError("strategy_id must be a non-empty string")
        object.__setattr__(self, "strategy_id", strategy_id)

    def to_dict(self) -> dict[str, Any]:
        """
        JSON-friendly representation.
        """

        return {
            "symbol": self.symbol,
            "option_type": self.option_type.value if isinstance(self.option_type, Enum) else str(self.option_type),
            "strike": float(self.strike),
            "expiry": self.expiry.isoformat(),
            "side": self.side.value if isinstance(self.side, Enum) else str(self.side),
            "quantity": int(self.quantity),
            "reason": self.reason,
            "strategy_id": self.strategy_id,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "OptionOrderIntent":
        """
        Create an OptionOrderIntent from a mapping (e.g., decoded JSON).
        """

        expiry = d.get("expiry")
        if isinstance(expiry, str):
            expiry = date.fromisoformat(expiry)
        return cls(
            symbol=d["symbol"],
            option_type=d["option_type"],
            strike=float(d["strike"]),
            expiry=expiry,  # type: ignore[arg-type]
            side=d["side"],
            quantity=int(d["quantity"]),
            reason=d["reason"],
            strategy_id=d["strategy_id"],
        )
