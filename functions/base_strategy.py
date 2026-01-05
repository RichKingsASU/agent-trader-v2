import logging

class BaseStrategy:
    """
    Base class for trading strategies, providing a common interface for initialization,
    event handling, and execution. This modular approach allows for easy integration and
    management of multiple strategies within the AgentTrader framework.

    Each strategy should inherit from this class and implement the abstract methods.
    """

    def __init__(self, strategy_id, symbol, trading_service):
        """
        Initializes the BaseStrategy.

        Args:
            strategy_id (str): A unique identifier for the strategy instance.
            symbol (str): The trading symbol the strategy will operate on.
            trading_service (TradingService): An object to interact with the trading platform.
        """
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.trading_service = trading_service
        self.logger = logging.getLogger(f"strategy.{strategy_id}")
        self.logger.info(f"Strategy {self.strategy_id} for {self.symbol} initialized.")

    def on_market_open(self, market_data):
        """
        Called when the market opens.
        """
        raise NotImplementedError("on_market_open must be implemented by subclasses.")

    def on_market_close(self, market_data):
        """
        Called when the market closes.
        """
        raise NotImplementedError("on_market_close must be implemented by subclasses.")

    def on_tick(self, market_data):
        """
        Called on every market data tick.
        """
        raise NotImplementedError("on_tick must be implemented by subclasses.")

    def execute_trade(self, trade_instruction):
        """
        Executes a trade.
        """
        self.logger.info(f"Executing trade: {trade_instruction}")
        # In a real implementation, this would interact with a trading service.
        pass