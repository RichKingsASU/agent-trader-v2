"""
Tests for the Backtesting Engine.
"""

import os
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../functions"))

from backtester import (
    Backtester,
    BacktestAccount,
    BacktestPosition,
)
from strategies.base_strategy import BaseStrategy, SignalType, TradingSignal


class MockStrategy(BaseStrategy):
    """Mock strategy for testing."""
    
    def __init__(self, signals=None):
        super().__init__()
        self.signals = signals or []
        self.call_count = 0
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        """Return predetermined signals for testing."""
        if self.call_count < len(self.signals):
            signal = self.signals[self.call_count]
            self.call_count += 1
            return signal
        
        # Default HOLD signal
        return TradingSignal(SignalType.HOLD, 0.0, "Default HOLD")


class TestBacktestPosition:
    """Test BacktestPosition class."""
    
    def test_position_creation(self):
        """Test creating a position."""
        entry_time = datetime.now()
        position = BacktestPosition(
            symbol="SPY",
            quantity=Decimal("10"),
            entry_price=Decimal("450.00"),
            entry_time=entry_time,
            side="long"
        )
        
        assert position.symbol == "SPY"
        assert position.quantity == Decimal("10")
        assert position.entry_price == Decimal("450.00")
        assert position.entry_time == entry_time
        assert position.side == "long"
        assert position.exit_price is None
        assert position.pnl is None
    
    def test_close_long_position_profit(self):
        """Test closing a long position with profit."""
        entry_time = datetime.now()
        exit_time = entry_time + timedelta(hours=1)
        
        position = BacktestPosition(
            symbol="SPY",
            quantity=Decimal("10"),
            entry_price=Decimal("450.00"),
            entry_time=entry_time,
            side="long"
        )
        
        pnl = position.close(Decimal("455.00"), exit_time)
        
        assert position.exit_price == Decimal("455.00")
        assert position.exit_time == exit_time
        assert pnl == Decimal("50.00")  # (455 - 450) * 10
        assert position.pnl == Decimal("50.00")
    
    def test_close_long_position_loss(self):
        """Test closing a long position with loss."""
        entry_time = datetime.now()
        exit_time = entry_time + timedelta(hours=1)
        
        position = BacktestPosition(
            symbol="SPY",
            quantity=Decimal("10"),
            entry_price=Decimal("450.00"),
            entry_time=entry_time,
            side="long"
        )
        
        pnl = position.close(Decimal("445.00"), exit_time)
        
        assert pnl == Decimal("-50.00")  # (445 - 450) * 10
    
    def test_position_to_dict(self):
        """Test converting position to dictionary."""
        entry_time = datetime.now()
        position = BacktestPosition(
            symbol="SPY",
            quantity=Decimal("10"),
            entry_price=Decimal("450.00"),
            entry_time=entry_time,
            side="long"
        )
        
        position.close(Decimal("455.00"), entry_time + timedelta(hours=1))
        
        pos_dict = position.to_dict()
        
        assert pos_dict["symbol"] == "SPY"
        assert pos_dict["quantity"] == 10.0
        assert pos_dict["entry_price"] == 450.00
        assert pos_dict["exit_price"] == 455.00
        assert pos_dict["pnl"] == 50.00
        assert pos_dict["side"] == "long"


class TestBacktestAccount:
    """Test BacktestAccount class."""
    
    def test_account_initialization(self):
        """Test account initialization."""
        initial_capital = Decimal("100000")
        account = BacktestAccount(initial_capital)
        
        assert account.initial_capital == initial_capital
        assert account.cash == initial_capital
        assert account.equity == initial_capital
        assert account.buying_power == initial_capital
        assert len(account.positions) == 0
        assert len(account.closed_positions) == 0
        assert len(account.trades) == 0
    
    def test_open_position_success(self):
        """Test opening a position successfully."""
        account = BacktestAccount(Decimal("100000"))
        timestamp = datetime.now()
        
        success = account.open_position(
            symbol="SPY",
            quantity=Decimal("100"),
            price=Decimal("450.00"),
            timestamp=timestamp,
            side="long"
        )
        
        assert success is True
        assert len(account.positions) == 1
        assert account.cash == Decimal("55000.00")  # 100000 - (100 * 450)
        assert len(account.trades) == 1
        assert account.trades[0]["type"] == "entry"
    
    def test_open_position_insufficient_cash(self):
        """Test opening a position with insufficient cash."""
        account = BacktestAccount(Decimal("1000"))
        timestamp = datetime.now()
        
        success = account.open_position(
            symbol="SPY",
            quantity=Decimal("100"),
            price=Decimal("450.00"),
            timestamp=timestamp,
            side="long"
        )
        
        assert success is False
        assert len(account.positions) == 0
        assert account.cash == Decimal("1000")
    
    def test_close_position(self):
        """Test closing a position."""
        account = BacktestAccount(Decimal("100000"))
        timestamp = datetime.now()
        
        # Open position
        account.open_position("SPY", Decimal("100"), Decimal("450.00"), timestamp, "long")
        
        # Close position
        position = account.positions[0]
        account.close_position(position, Decimal("455.00"), timestamp + timedelta(hours=1))
        
        assert len(account.positions) == 0
        assert len(account.closed_positions) == 1
        assert account.cash == Decimal("100500.00")  # 55000 + (100 * 455)
        assert len(account.trades) == 2
        assert account.trades[1]["type"] == "exit"
        assert account.trades[1]["pnl"] == 500.0
    
    def test_close_all_positions(self):
        """Test closing all positions."""
        account = BacktestAccount(Decimal("100000"))
        timestamp = datetime.now()
        
        # Open multiple positions
        account.open_position("SPY", Decimal("50"), Decimal("450.00"), timestamp, "long")
        account.open_position("SPY", Decimal("30"), Decimal("452.00"), timestamp, "long")
        
        assert len(account.positions) == 2
        
        # Close all
        account.close_all_positions(Decimal("455.00"), timestamp + timedelta(hours=1))
        
        assert len(account.positions) == 0
        assert len(account.closed_positions) == 2
    
    def test_record_equity(self):
        """Test recording equity curve."""
        account = BacktestAccount(Decimal("100000"))
        timestamp = datetime.now()
        
        # Record initial equity
        account.record_equity(timestamp, Decimal("450.00"))
        
        assert len(account.equity_curve) == 1
        assert account.equity_curve[0]["equity"] == 100000.0
        
        # Open position and record again
        account.open_position("SPY", Decimal("100"), Decimal("450.00"), timestamp, "long")
        account.record_equity(timestamp + timedelta(minutes=1), Decimal("455.00"))
        
        assert len(account.equity_curve) == 2
        # Equity = cash + (qty * current_price) = 55000 + (100 * 455) = 100500
        assert account.equity_curve[1]["equity"] == 100500.0
    
    def test_get_snapshot(self):
        """Test getting account snapshot."""
        account = BacktestAccount(Decimal("100000"))
        timestamp = datetime.now()
        
        # Open position
        account.open_position("SPY", Decimal("100"), Decimal("450.00"), timestamp, "long")
        
        snapshot = account.get_snapshot()
        
        assert "equity" in snapshot
        assert "buying_power" in snapshot
        assert "cash" in snapshot
        assert "positions" in snapshot
        assert len(snapshot["positions"]) == 1
        assert snapshot["positions"][0]["symbol"] == "SPY"
        assert snapshot["positions"][0]["qty"] == 100.0


class TestBacktester:
    """Test Backtester class."""
    
    @pytest.fixture
    def mock_bars(self):
        """Create mock bar data."""
        base_time = datetime(2024, 1, 1, 9, 30, tzinfo=None)
        bars = []
        
        for i in range(10):
            bars.append({
                "timestamp": base_time + timedelta(minutes=i),
                "open": 450.0 + i * 0.1,
                "high": 450.5 + i * 0.1,
                "low": 449.5 + i * 0.1,
                "close": 450.0 + i * 0.1,
                "volume": 1000000
            })
        
        return bars
    
    @patch.dict(os.environ, {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"})
    def test_backtester_initialization(self):
        """Test backtester initialization."""
        strategy = MockStrategy()
        
        backtester = Backtester(
            strategy=strategy,
            symbol="SPY",
            start_date="2024-01-01",
            end_date="2024-01-31",
            initial_capital=100000.0
        )
        
        assert backtester.strategy == strategy
        assert backtester.symbol == "SPY"
        assert backtester.initial_capital == Decimal("100000")
        assert backtester.start_date.year == 2024
        assert backtester.start_date.month == 1
        assert backtester.start_date.day == 1
    
    @patch.dict(os.environ, {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"})
    def test_backtester_run_hold_strategy(self, mock_bars):
        """Test running backtest with HOLD strategy."""
        # Strategy that only holds
        strategy = MockStrategy(signals=[
            TradingSignal(SignalType.HOLD, 0.0, "Hold") for _ in range(10)
        ])
        
        backtester = Backtester(
            strategy=strategy,
            symbol="SPY",
            start_date="2024-01-01",
            end_date="2024-01-31",
            initial_capital=100000.0
        )
        
        # Mock fetch_data
        with patch.object(backtester, 'fetch_data', return_value=mock_bars):
            results = backtester.run()
        
        # Check results structure
        assert "metrics" in results
        assert "equity_curve" in results
        assert "benchmark_curve" in results
        assert "trades" in results
        assert "config" in results
        
        # Should have no trades for HOLD strategy
        assert results["metrics"]["total_trades"] == 0
        
        # Equity should be unchanged
        assert results["metrics"]["final_equity"] == 100000.0
    
    @patch.dict(os.environ, {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"})
    def test_backtester_run_buy_strategy(self, mock_bars):
        """Test running backtest with BUY strategy."""
        # Strategy that buys on first bar
        signals = [TradingSignal(SignalType.BUY, 0.5, "Buy signal")]
        signals.extend([TradingSignal(SignalType.HOLD, 0.0, "Hold") for _ in range(9)])
        
        strategy = MockStrategy(signals=signals)
        
        backtester = Backtester(
            strategy=strategy,
            symbol="SPY",
            start_date="2024-01-01",
            end_date="2024-01-31",
            initial_capital=100000.0
        )
        
        # Mock fetch_data
        with patch.object(backtester, 'fetch_data', return_value=mock_bars):
            results = backtester.run()
        
        # Should have at least 1 trade
        assert results["metrics"]["total_trades"] >= 1
        
        # Check that equity curve has entries
        assert len(results["equity_curve"]) == len(mock_bars)
    
    @patch.dict(os.environ, {"APCA_API_KEY_ID": "test_key", "APCA_API_SECRET_KEY": "test_secret"})
    def test_calculate_metrics(self, mock_bars):
        """Test metrics calculation."""
        strategy = MockStrategy()
        
        backtester = Backtester(
            strategy=strategy,
            symbol="SPY",
            start_date="2024-01-01",
            end_date="2024-01-31",
            initial_capital=100000.0
        )
        
        # Mock fetch_data and run
        with patch.object(backtester, 'fetch_data', return_value=mock_bars):
            results = backtester.run()
        
        metrics = results["metrics"]
        
        # Check all required metrics exist
        assert "initial_capital" in metrics
        assert "final_equity" in metrics
        assert "total_return" in metrics
        assert "benchmark_return" in metrics
        assert "alpha" in metrics
        assert "sharpe_ratio" in metrics
        assert "max_drawdown" in metrics
        assert "win_rate" in metrics
        assert "total_trades" in metrics
        assert "winning_trades" in metrics
        assert "losing_trades" in metrics
        assert "avg_win" in metrics
        assert "avg_loss" in metrics
        assert "profit_factor" in metrics
        
        # Check metric types
        assert isinstance(metrics["total_return"], float)
        assert isinstance(metrics["sharpe_ratio"], float)
        assert isinstance(metrics["max_drawdown"], float)
        assert isinstance(metrics["win_rate"], float)
    
    def test_backtester_missing_credentials(self):
        """Test that backtester raises error without API credentials."""
        strategy = MockStrategy()
        
        with pytest.raises(ValueError, match="Alpaca API credentials required"):
            Backtester(
                strategy=strategy,
                symbol="SPY",
                start_date="2024-01-01",
                end_date="2024-01-31",
                initial_capital=100000.0
            )


def test_integration_with_gamma_scalper():
    """Integration test with GammaScalper strategy."""
    # This is a smoke test - just ensure imports work
    from strategies.gamma_scalper import GammaScalper
    
    strategy = GammaScalper(config={
        "threshold": 0.15,
        "gex_positive_multiplier": 0.5,
        "gex_negative_multiplier": 1.5
    })
    
    assert strategy is not None
    assert strategy.get_strategy_name() == "GammaScalper"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
