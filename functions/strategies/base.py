from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.
    """

    @abstractmethod
    def evaluate(self, market_data: Dict[str, Any], account_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate the strategy based on market data and account snapshot.

        Args:
            market_data: A dictionary containing market data.
            account_snapshot: A dictionary containing the current account snapshot.

        Returns:
            A dictionary containing the trading signal.
        """
        pass