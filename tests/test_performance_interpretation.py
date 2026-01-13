"""
Tests for performance interpretation (human-readable signals).
"""

from backend.analytics.performance_interpretation import (
    compute_expectancy_per_trade,
    interpret_daily_summaries,
)
from backend.analytics.trade_parser import DailyPnLSummary


def test_compute_expectancy_per_trade_basic():
    # 50% win rate, avg win +10, avg loss -5 => expectancy = 2.5 per trade
    ex = compute_expectancy_per_trade(win_rate_pct=50.0, avg_win=10.0, avg_loss=-5.0)
    assert ex == 2.5


def test_interpret_daily_summaries_labels_and_threshold_logic():
    daily = [
        DailyPnLSummary(
            date="2025-01-01",
            total_pnl=10.0,
            gross_pnl=12.0,
            fees=2.0,
            trades_count=4,
            winning_trades=2,
            losing_trades=2,
            win_rate=50.0,
            avg_win=10.0,
            avg_loss=-5.0,
            largest_win=10.0,
            largest_loss=-5.0,
            symbols_traded=["SPY"],
        ),
        DailyPnLSummary(
            date="2025-01-02",
            total_pnl=0.5,
            gross_pnl=1.0,
            fees=0.5,
            trades_count=2,
            winning_trades=1,
            losing_trades=1,
            win_rate=50.0,
            avg_win=1.0,
            avg_loss=-0.5,
            largest_win=1.0,
            largest_loss=-0.5,
            symbols_traded=["AAPL"],
        ),
        DailyPnLSummary(
            date="2025-01-03",
            total_pnl=-2.0,
            gross_pnl=-1.0,
            fees=1.0,
            trades_count=2,
            winning_trades=0,
            losing_trades=2,
            win_rate=0.0,
            avg_win=0.0,
            avg_loss=-1.0,
            largest_win=0.0,
            largest_loss=-1.0,
            symbols_traded=["TSLA"],
        ),
    ]

    signals, logic = interpret_daily_summaries(daily, flat_threshold_abs=1.0)
    assert [s.label for s in signals] == ["Profitable", "Flat", "Losing"]

    assert logic["flat_threshold_abs"] == 1.0
    assert logic["profitable_if"] == "net_pnl >= +1.0"
    assert logic["losing_if"] == "net_pnl <= -1.0"
    assert logic["flat_if"] == "-1.0 < net_pnl < +1.0"

    # Sanity-check expectancy fields
    assert signals[0].expectancy_gross_per_trade == 2.5
    assert signals[0].expectancy_net_per_trade == 10.0 / 4

