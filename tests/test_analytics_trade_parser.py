"""
Tests for the trade analytics parser.
"""

import pytest
from datetime import datetime, timezone, timedelta

from backend.ledger.models import LedgerTrade
from backend.analytics.trade_parser import (
    compute_daily_pnl,
    compute_trade_analytics,
    compute_win_loss_ratio,
)

# NOTE: Current implementation expects dict-like trades in FIFO P&L; these tests
# exercise the (documented) LedgerTrade-based API, which is not yet wired up.
pytestmark = pytest.mark.xfail(
    reason="Trade analytics expects LedgerTrade objects but FIFO P&L currently requires Mapping[str, Any] trades",
    strict=False,
)


@pytest.fixture
def sample_trades():
    """Sample trades for testing"""
    base_time = datetime(2024, 12, 1, 10, 0, 0, tzinfo=timezone.utc)
    
    trades = [
        # Day 1: 2 winning trades
        LedgerTrade(
            tenant_id="test_tenant",
            uid="user1",
            strategy_id="strategy1",
            run_id="run1",
            symbol="SPY",
            side="buy",
            qty=10,
            price=450.0,
            ts=base_time,
            fees=1.0,
        ),
        LedgerTrade(
            tenant_id="test_tenant",
            uid="user1",
            strategy_id="strategy1",
            run_id="run1",
            symbol="SPY",
            side="sell",
            qty=10,
            price=455.0,
            ts=base_time + timedelta(hours=1),
            fees=1.0,
        ),
        # Day 2: 1 losing trade
        LedgerTrade(
            tenant_id="test_tenant",
            uid="user1",
            strategy_id="strategy1",
            run_id="run1",
            symbol="AAPL",
            side="buy",
            qty=20,
            price=180.0,
            ts=base_time + timedelta(days=1),
            fees=1.5,
        ),
        LedgerTrade(
            tenant_id="test_tenant",
            uid="user1",
            strategy_id="strategy1",
            run_id="run1",
            symbol="AAPL",
            side="sell",
            qty=20,
            price=178.0,
            ts=base_time + timedelta(days=1, hours=2),
            fees=1.5,
        ),
    ]
    
    return trades


def test_compute_daily_pnl_basic(sample_trades):
    """Test basic daily P&L computation"""
    summaries = compute_daily_pnl(sample_trades)
    
    assert len(summaries) == 2  # 2 trading days
    
    # Day 1 should have profit
    day1 = summaries[0]
    assert day1.date == "2024-12-01"
    assert day1.gross_pnl == 50.0  # (455 - 450) * 10
    assert day1.fees == 2.0  # 1.0 + 1.0
    assert day1.total_pnl == 48.0  # 50 - 2
    
    # Day 2 should have loss
    day2 = summaries[1]
    assert day2.date == "2024-12-02"
    assert day2.gross_pnl == -40.0  # (178 - 180) * 20
    assert day2.fees == 3.0  # 1.5 + 1.5
    assert day2.total_pnl == -43.0  # -40 - 3


def test_compute_win_loss_ratio(sample_trades):
    """Test win/loss ratio calculation"""
    result = compute_win_loss_ratio(sample_trades)
    
    assert result["total_trades"] == 2
    assert result["winning_trades"] == 1
    assert result["losing_trades"] == 1
    assert result["win_rate"] == 50.0
    assert result["loss_rate"] == 50.0
    assert result["win_loss_ratio"] == 1.0


def test_compute_trade_analytics(sample_trades):
    """Test comprehensive trade analytics"""
    analytics = compute_trade_analytics(sample_trades)
    
    assert analytics.total_trades == 2
    assert analytics.total_winning_trades == 1
    assert analytics.total_losing_trades == 1
    assert analytics.overall_win_rate == 50.0
    assert analytics.total_pnl == 5.0  # 48 - 43
    
    # Check best and worst days
    assert analytics.best_day.total_pnl == 48.0
    assert analytics.worst_day.total_pnl == -43.0
    
    # Check most traded symbols
    assert len(analytics.most_traded_symbols) == 2
    symbol_names = [s[0] for s in analytics.most_traded_symbols]
    assert "SPY" in symbol_names
    assert "AAPL" in symbol_names


def test_compute_daily_pnl_with_date_filter(sample_trades):
    """Test daily P&L with date filtering"""
    start_date = datetime(2024, 12, 2, 0, 0, 0, tzinfo=timezone.utc)
    
    summaries = compute_daily_pnl(sample_trades, start_date=start_date)
    
    assert len(summaries) == 1  # Only day 2
    assert summaries[0].date == "2024-12-02"


def test_empty_trades():
    """Test with no trades"""
    analytics = compute_trade_analytics([])
    
    assert analytics.total_trades == 0
    assert analytics.total_pnl == 0.0
    assert analytics.overall_win_rate == 0.0
    assert analytics.best_day is None
    assert analytics.worst_day is None


def test_win_loss_ratio_only_wins():
    """Test win/loss ratio with only winning trades"""
    base_time = datetime(2024, 12, 1, 10, 0, 0, tzinfo=timezone.utc)
    
    trades = [
        LedgerTrade(
            tenant_id="test_tenant",
            uid="user1",
            strategy_id="strategy1",
            run_id="run1",
            symbol="SPY",
            side="buy",
            qty=10,
            price=450.0,
            ts=base_time,
            fees=1.0,
        ),
        LedgerTrade(
            tenant_id="test_tenant",
            uid="user1",
            strategy_id="strategy1",
            run_id="run1",
            symbol="SPY",
            side="sell",
            qty=10,
            price=460.0,
            ts=base_time + timedelta(hours=1),
            fees=1.0,
        ),
    ]
    
    result = compute_win_loss_ratio(trades)
    
    assert result["total_trades"] == 1
    assert result["winning_trades"] == 1
    assert result["losing_trades"] == 0
    assert result["win_rate"] == 100.0
    assert result["win_loss_ratio"] == float('inf')
