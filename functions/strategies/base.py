from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    """

    def __init__(self, *, name: str, config: Optional[Dict[str, Any]] = None) -> None:
        self.name = str(name)
        self.config: Dict[str, Any] = dict(config or {})

    @abstractmethod
    async def evaluate(self, market_data: Dict[str, Any], account_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate the strategy based on market data and account snapshot.

        Args:
            market_data: A dictionary containing market data.
            account_snapshot: A dictionary containing the current account snapshot.

        Returns:
            A dictionary containing the trading signal.
        """
        pass