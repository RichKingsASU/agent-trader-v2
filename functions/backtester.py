"""
Backtesting Engine for Trading Strategies.

This module provides a comprehensive backtesting framework that:
1. Fetches historical market data using Alpaca
2. Simulates strategy execution with realistic fills
3. Calculates performance metrics (Sharpe Ratio, Max Drawdown, Win Rate)
4. Tracks equity curves and trade statistics

Usage:
    from backtester import Backtester
    from strategies.gamma_scalper import GammaScalper
    
    backtester = Backtester(
        strategy=GammaScalper(),
        symbol="SPY",
        start_date="2024-11-01",
        end_date="2024-12-01",
        initial_capital=100000
    )
    
    results = backtester.run()
    print(f"Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['max_drawdown']:.2%}")
"""

import logging
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union
import pytz

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from strategies.base_strategy import BaseStrategy, SignalType, TradingSignal

logger = logging.getLogger(__name__)


class BacktestPosition:
    """Represents a position in the backtest portfolio."""
    
    def __init__(self, symbol: str, quantity: Decimal, entry_price: Decimal, 
                 entry_time: datetime, side: str = "long"):
        self.symbol = symbol
        self.quantity = quantity
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.side = side
        self.exit_price: Optional[Decimal] = None
        self.exit_time: Optional[datetime] = None
        self.pnl: Optional[Decimal] = None
    
    def close(self, exit_price: Decimal, exit_time: datetime) -> Decimal:
        """Close the position and calculate PnL."""
        self.exit_price = exit_price
        self.exit_time = exit_time
        
        if self.side == "long":
            self.pnl = (exit_price - self.entry_price) * self.quantity
        else:  # short
            self.pnl = (self.entry_price - exit_price) * self.quantity
        
        return self.pnl
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert position to dictionary."""
        return {
            "symbol": self.symbol,
            "quantity": float(self.quantity),
            "entry_price": float(self.entry_price),
            "entry_time": self.entry_time.isoformat(),
            "exit_price": float(self.exit_price) if self.exit_price else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "pnl": float(self.pnl) if self.pnl else None,
            "side": self.side
        }


class BacktestAccount:
    """Simulates a trading account for backtesting."""
    
    def __init__(self, initial_capital: Decimal):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: List[BacktestPosition] = []
        self.closed_positions: List[BacktestPosition] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
    
    @property
    def equity(self) -> Decimal:
        """Current total equity (cash + position value)."""
        position_value = sum(
            pos.quantity * pos.entry_price for pos in self.positions
        )
        return self.cash + position_value
    
    @property
    def buying_power(self) -> Decimal:
        """Available buying power (simplified as cash for now)."""
        return self.cash
    
    def open_position(self, symbol: str, quantity: Decimal, price: Decimal,
                     timestamp: datetime, side: str = "long") -> bool:
        """Open a new position."""
        cost = quantity * price
        
        if cost > self.cash:
            logger.warning(f"Insufficient cash: ${float(self.cash):.2f} < ${float(cost):.2f}")
            return False
        
        position = BacktestPosition(symbol, quantity, price, timestamp, side)
        self.positions.append(position)
        self.cash -= cost
        
        self.trades.append({
            "timestamp": timestamp.isoformat(),
            "symbol": symbol,
            "side": "buy" if side == "long" else "sell",
            "quantity": float(quantity),
            "price": float(price),
            "type": "entry"
        })
        
        logger.info(f"Opened {side} position: {symbol} x{quantity} @ ${price}")
        return True
    
    def close_position(self, position: BacktestPosition, price: Decimal,
                      timestamp: datetime) -> None:
        """Close an existing position."""
        pnl = position.close(price, timestamp)
        self.cash += position.quantity * price
        self.positions.remove(position)
        self.closed_positions.append(position)
        
        self.trades.append({
            "timestamp": timestamp.isoformat(),
            "symbol": position.symbol,
            "side": "sell" if position.side == "long" else "buy",
            "quantity": float(position.quantity),
            "price": float(price),
            "type": "exit",
            "pnl": float(pnl)
        })
        
        logger.info(f"Closed position: {position.symbol} @ ${price}, PnL: ${float(pnl):.2f}")
    
    def close_all_positions(self, price: Decimal, timestamp: datetime) -> None:
        """Close all open positions."""
        for position in list(self.positions):
            self.close_position(position, price, timestamp)
    
    def record_equity(self, timestamp: datetime, price: Decimal) -> None:
        """Record current equity for the equity curve."""
        # Mark-to-market positions
        position_value = sum(pos.quantity * price for pos in self.positions)
        total_equity = self.cash + position_value
        
        self.equity_curve.append({
            "timestamp": timestamp.isoformat(),
            "equity": float(total_equity),
            "cash": float(self.cash),
            "position_value": float(position_value),
            "num_positions": len(self.positions)
        })
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current account snapshot for strategy evaluation."""
        return {
            "equity": str(self.equity),
            "buying_power": str(self.buying_power),
            "cash": str(self.cash),
            "positions": [
                {
                    "symbol": pos.symbol,
                    "qty": float(pos.quantity),
                    "entry_price": float(pos.entry_price),
                    "greeks": {}  # Simplified for now
                }
                for pos in self.positions
            ]
        }


class Backtester:
    """
    Backtesting engine that simulates strategy execution on historical data.
    """
    
    def __init__(
        self,
        strategy: BaseStrategy,
        symbol: str = "SPY",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        initial_capital: float = 100000.0,
        commission: float = 0.0,
        slippage: float = 0.0,
        alpaca_api_key: Optional[str] = None,
        alpaca_secret_key: Optional[str] = None
    ):
        """
        Initialize the backtester.
        
        Args:
            strategy: Strategy instance to backtest
            symbol: Symbol to backtest (default: SPY)
            start_date: Start date in YYYY-MM-DD format (default: 30 days ago)
            end_date: End date in YYYY-MM-DD format (default: today)
            initial_capital: Starting capital in USD
            commission: Commission per trade (not yet implemented)
            slippage: Slippage in decimal (not yet implemented)
            alpaca_api_key: Alpaca API key (or use env var APCA_API_KEY_ID)
            alpaca_secret_key: Alpaca secret key (or use env var APCA_API_SECRET_KEY)
        """
        self.strategy = strategy
        self.symbol = symbol.upper()
        self.initial_capital = Decimal(str(initial_capital))
        self.commission = Decimal(str(commission))
        self.slippage = Decimal(str(slippage))
        
        # Date range
        if end_date is None:
            self.end_date = datetime.now(pytz.UTC).date()
        else:
            self.end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        if start_date is None:
            self.start_date = (self.end_date - timedelta(days=30))
        else:
            self.start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        
        # Alpaca client
        api_key = alpaca_api_key or os.getenv("APCA_API_KEY_ID")
        secret_key = alpaca_secret_key or os.getenv("APCA_API_SECRET_KEY")
        
        if not api_key or not secret_key:
            raise ValueError(
                "Alpaca API credentials required. Set APCA_API_KEY_ID and "
                "APCA_API_SECRET_KEY environment variables or pass as parameters."
            )
        
        self.data_client = StockHistoricalDataClient(api_key, secret_key)
        
        # Results storage
        self.account: Optional[BacktestAccount] = None
        self.benchmark_equity_curve: List[Dict[str, Any]] = []
        
        logger.info(
            f"Backtester initialized: {self.symbol} from {self.start_date} to {self.end_date}, "
            f"Capital: ${float(self.initial_capital):,.2f}"
        )
    
    def fetch_data(self) -> List[Dict[str, Any]]:
        """
        Fetch historical 1-minute bar data from Alpaca.
        
        Returns:
            List of bar dictionaries with timestamp, open, high, low, close, volume
        """
        logger.info(f"Fetching historical data for {self.symbol}...")
        
        request = StockBarsRequest(
            symbol_or_symbols=self.symbol,
            timeframe=TimeFrame.Minute,
            start=datetime.combine(self.start_date, datetime.min.time()).replace(tzinfo=pytz.UTC),
            end=datetime.combine(self.end_date, datetime.max.time()).replace(tzinfo=pytz.UTC)
        )
        
        bars = self.data_client.get_stock_bars(request)
        
        # Convert to list of dictionaries
        data = []
        for bar in bars[self.symbol]:
            data.append({
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume)
            })
        
        logger.info(f"Fetched {len(data)} bars from {data[0]['timestamp']} to {data[-1]['timestamp']}")
        return data
    
    def run(self) -> Dict[str, Any]:
        """
        Run the backtest simulation.
        
        Returns:
            Dictionary with backtest results including metrics and equity curve
        """
        logger.info("Starting backtest...")
        
        # Fetch data
        bars = self.fetch_data()
        
        if not bars:
            raise ValueError("No data available for backtesting")
        
        # Initialize account
        self.account = BacktestAccount(self.initial_capital)
        
        # Initialize benchmark (buy and hold)
        benchmark_shares = self.initial_capital / Decimal(str(bars[0]["close"]))
        benchmark_cost = benchmark_shares * Decimal(str(bars[0]["close"]))
        
        # Run simulation
        for i, bar in enumerate(bars):
            timestamp = bar["timestamp"]
            price = Decimal(str(bar["close"]))
            
            # Prepare market data for strategy
            market_data = {
                "symbol": self.symbol,
                "price": float(price),
                "timestamp": timestamp.isoformat(),
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
                "greeks": {},  # Simplified
                "gex_status": "neutral"  # Simplified
            }
            
            # Get account snapshot
            account_snapshot = self.account.get_snapshot()
            
            # Evaluate strategy
            try:
                signal = self.strategy.evaluate(market_data, account_snapshot)
            except Exception as e:
                logger.error(f"Strategy evaluation error at {timestamp}: {e}")
                signal = TradingSignal(SignalType.HOLD, self.symbol, confidence=0.0, reasoning=f"Error: {e}")
            
            # Execute signal
            self._execute_signal(signal, price, timestamp)
            
            # Record equity
            self.account.record_equity(timestamp, price)
            
            # Record benchmark
            benchmark_value = benchmark_shares * price
            self.benchmark_equity_curve.append({
                "timestamp": timestamp.isoformat(),
                "equity": float(benchmark_value)
            })
            
            # Log progress every 100 bars
            if (i + 1) % 100 == 0:
                logger.info(
                    f"Progress: {i + 1}/{len(bars)} bars, "
                    f"Equity: ${float(self.account.equity):,.2f}"
                )
        
        # Close any remaining positions at the end
        if self.account.positions:
            final_price = Decimal(str(bars[-1]["close"]))
            final_time = bars[-1]["timestamp"]
            self.account.close_all_positions(final_price, final_time)
        
        # Calculate metrics
        metrics = self._calculate_metrics()
        
        logger.info("Backtest complete!")
        logger.info(f"Final Equity: ${metrics['final_equity']:,.2f}")
        logger.info(f"Total Return: {metrics['total_return']:.2%}")
        logger.info(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
        logger.info(f"Max Drawdown: {metrics['max_drawdown']:.2%}")
        logger.info(f"Win Rate: {metrics['win_rate']:.2%}")
        
        return {
            "metrics": metrics,
            "equity_curve": self.account.equity_curve,
            "benchmark_curve": self.benchmark_equity_curve,
            "trades": self.account.trades,
            "closed_positions": [pos.to_dict() for pos in self.account.closed_positions],
            "config": {
                "symbol": self.symbol,
                "start_date": self.start_date.isoformat(),
                "end_date": self.end_date.isoformat(),
                "initial_capital": float(self.initial_capital),
                "strategy": self.strategy.get_strategy_name()
            }
        }
    
    def _execute_signal(self, signal: TradingSignal, price: Decimal, 
                       timestamp: datetime) -> None:
        """Execute a trading signal."""
        if signal.signal_type == SignalType.HOLD:
            return
        
        if signal.signal_type == SignalType.CLOSE_ALL:
            if self.account.positions:
                logger.info(f"Signal: CLOSE_ALL - {signal.reasoning}")
                self.account.close_all_positions(price, timestamp)
            return
        
        # Calculate position size based on confidence
        # Use confidence as allocation percentage
        allocation = signal.confidence
        if allocation <= 0:
            return
        
        target_value = self.account.buying_power * Decimal(str(allocation))
        quantity = (target_value / price).quantize(Decimal("1"))
        
        if quantity <= 0:
            return
        
        if signal.signal_type == SignalType.BUY:
            logger.info(f"Signal: BUY - {signal.reasoning}")
            self.account.open_position(self.symbol, quantity, price, timestamp, "long")
        
        elif signal.signal_type == SignalType.SELL:
            # Close existing positions or open short (simplified: just close)
            if self.account.positions:
                logger.info(f"Signal: SELL - {signal.reasoning}")
                for position in list(self.account.positions):
                    self.account.close_position(position, price, timestamp)
    
    def _calculate_metrics(self) -> Dict[str, Any]:
        """Calculate performance metrics."""
        if not self.account or not self.account.equity_curve:
            return {}
        
        # Extract equity values
        equity_values = [point["equity"] for point in self.account.equity_curve]
        benchmark_values = [point["equity"] for point in self.benchmark_equity_curve]
        
        # Basic metrics
        final_equity = Decimal(str(equity_values[-1]))
        total_return = (final_equity - self.initial_capital) / self.initial_capital
        
        benchmark_final = Decimal(str(benchmark_values[-1]))
        benchmark_return = (benchmark_final - self.initial_capital) / self.initial_capital
        
        # Sharpe Ratio (annualized, assuming 252 trading days, 390 minutes per day)
        returns = [
            (Decimal(str(equity_values[i])) - Decimal(str(equity_values[i-1]))) / Decimal(str(equity_values[i-1]))
            for i in range(1, len(equity_values))
        ]
        
        if returns:
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_return = variance.sqrt() if variance > 0 else Decimal("0")
            
            # Annualize: 252 days * 390 minutes
            periods_per_year = 252 * 390
            sharpe_ratio = (mean_return / std_return * Decimal(str(periods_per_year)).sqrt()) if std_return > 0 else Decimal("0")
        else:
            sharpe_ratio = Decimal("0")
        
        # Maximum Drawdown
        max_equity = Decimal(str(equity_values[0]))
        max_drawdown = Decimal("0")
        
        for equity in equity_values:
            equity_dec = Decimal(str(equity))
            if equity_dec > max_equity:
                max_equity = equity_dec
            
            drawdown = (max_equity - equity_dec) / max_equity if max_equity > 0 else Decimal("0")
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Win Rate
        winning_trades = [pos for pos in self.account.closed_positions if pos.pnl and pos.pnl > 0]
        total_trades = len(self.account.closed_positions)
        win_rate = Decimal(str(len(winning_trades))) / Decimal(str(total_trades)) if total_trades > 0 else Decimal("0")
        
        # Average win/loss
        if winning_trades:
            avg_win = sum(pos.pnl for pos in winning_trades) / len(winning_trades)
        else:
            avg_win = Decimal("0")
        
        losing_trades = [pos for pos in self.account.closed_positions if pos.pnl and pos.pnl < 0]
        if losing_trades:
            avg_loss = sum(pos.pnl for pos in losing_trades) / len(losing_trades)
        else:
            avg_loss = Decimal("0")
        
        return {
            "initial_capital": float(self.initial_capital),
            "final_equity": float(final_equity),
            "total_return": float(total_return),
            "benchmark_return": float(benchmark_return),
            "alpha": float(total_return - benchmark_return),
            "sharpe_ratio": float(sharpe_ratio),
            "max_drawdown": float(max_drawdown),
            "win_rate": float(win_rate),
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "avg_win": float(avg_win),
            "avg_loss": float(avg_loss),
            "profit_factor": float(avg_win / abs(avg_loss)) if avg_loss != 0 else 0.0
        }


def run_backtest_example():
    """Example usage of the backtester."""
    from strategies.gamma_scalper import GammaScalper
    
    # Initialize strategy
    strategy = GammaScalper(config={
        "threshold": 0.15,
        "gex_positive_multiplier": 0.5,
        "gex_negative_multiplier": 1.5
    })
    
    # Create backtester
    backtester = Backtester(
        strategy=strategy,
        symbol="SPY",
        start_date="2024-11-01",
        end_date="2024-12-01",
        initial_capital=100000.0
    )
    
    # Run backtest
    results = backtester.run()
    
    # Print results
    print("\n" + "="*60)
    print("BACKTEST RESULTS")
    print("="*60)
    print(f"\nStrategy: {results['config']['strategy']}")
    print(f"Symbol: {results['config']['symbol']}")
    print(f"Period: {results['config']['start_date']} to {results['config']['end_date']}")
    print(f"\nInitial Capital: ${results['metrics']['initial_capital']:,.2f}")
    print(f"Final Equity: ${results['metrics']['final_equity']:,.2f}")
    print(f"Total Return: {results['metrics']['total_return']:.2%}")
    print(f"Benchmark Return: {results['metrics']['benchmark_return']:.2%}")
    print(f"Alpha: {results['metrics']['alpha']:.2%}")
    print(f"\nSharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {results['metrics']['max_drawdown']:.2%}")
    print(f"\nTotal Trades: {results['metrics']['total_trades']}")
    print(f"Win Rate: {results['metrics']['win_rate']:.2%}")
    print(f"Avg Win: ${results['metrics']['avg_win']:,.2f}")
    print(f"Avg Loss: ${results['metrics']['avg_loss']:,.2f}")
    print(f"Profit Factor: {results['metrics']['profit_factor']:.2f}")
    print("="*60)
    
    return results


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Run example
    run_backtest_example()
