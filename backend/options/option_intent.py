from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Dict


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass(frozen=True)
class OptionOrderIntent:
    """
    Protocol-layer option intent.

    This is intentionally minimal and broker-agnostic.
    """

    underlying: str
    option_type: OptionType  # CALL / PUT
    strike: float
    expiry: date
    contracts: int
    side: Side
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)

