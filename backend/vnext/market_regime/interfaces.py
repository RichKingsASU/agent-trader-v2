from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class MarketRegime(str, Enum):
    """
    Advisory market "weather" label.

    Notes:
    - This is intentionally coarse and strategy-agnostic.
    - A strategy may *down-weight* signals based on regime, but regime must not
      directly trigger execution behavior.
    """

    UNKNOWN = "UNKNOWN"

    # Broad directional context
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"

    # Price action shape
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE_BOUND = "RANGE_BOUND"

    # Volatility / uncertainty overlays
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    EVENT_RISK = "EVENT_RISK"


@dataclass(frozen=True, slots=True)
class RegimeSnapshot:
    """
    Point-in-time market regime assessment (schema-only).

    Contract:
    - `confidence` is normalized to [0.0, 1.0].
    - `as_of_utc` is timezone-aware and in UTC.
    - `metrics` is optional, read-only metadata that can help with debugging,
      monitoring, and post-trade / backtest analysis (no execution directives).
    """

    regime: MarketRegime
    confidence: float
    as_of_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str | None = None
    metrics: Mapping[str, Any] = field(default_factory=dict)
    notes: str | None = None


def get_current_regime(symbol: str | None = None) -> RegimeSnapshot:
    """
    Interface stub: retrieve the current advisory market regime.

    This function is intentionally *not implemented* in vNEXT schema modules.
    Implementations must live in a separate runtime/service layer.
    """

    raise NotImplementedError(
        "Schema-only interface: provide an implementation of get_current_regime() "
        "in a runtime layer (no execution logic in vNEXT)."
    )

