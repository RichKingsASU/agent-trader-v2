from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies (async interface).

    This is the canonical interface used by unit tests and newer async strategy
    runners. Concrete strategies MUST implement `evaluate`.
    """

    def __init__(self, *, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        self.name = str(name)
        self.config: Dict[str, Any] = dict(config or {})

    @abstractmethod
    async def evaluate(self, market_data: Dict[str, Any], account_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate the strategy based on market data and account snapshot.
        """
        raise NotImplementedError