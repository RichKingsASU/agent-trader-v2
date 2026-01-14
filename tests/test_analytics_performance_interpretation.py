"""
Tests for daily performance interpretation.
"""

from backend.analytics.performance_interpretation import (
    DailySummaryThresholds,
    classify_day,
    compute_expectancy_per_trade,
    emit_daily_summary,
)

from backend.analytics.trade_parser import DailyPnLSummary


def test_compute_expectancy_per_trade_gross_and_net():
    # 60% win rate, avg win +100, avg loss -80, fee 2 per trade
    out = compute_expectancy_per_trade(
        win_rate_pct=60.0,
        avg_win=100.0,
        avg_loss=-80.0,
        avg_fee_per_trade=2.0,
    )

    # Base expectancy: 0.6*100 + 0.4*(-80) = 28
    assert out["expectancy_per_trade"] == 28.0

    # Fee-adjusted expectancy subtracts avg_fee_per_trade
    assert out["expectancy_fee_adjusted_per_trade"] == 26.0


def test_classify_day_thresholds():
    th = DailySummaryThresholds(flat_pnl_abs=10.0)

    assert classify_day(net_pnl=0.0, thresholds=th) == "FLAT"
    assert classify_day(net_pnl=9.99, thresholds=th) == "FLAT"
    assert classify_day(net_pnl=-10.0, thresholds=th) == "FLAT"
    assert classify_day(net_pnl=10.01, thresholds=th) == "PROFITABLE"
    assert classify_day(net_pnl=-10.01, thresholds=th) == "LOSING"


def test_emit_daily_summary_includes_required_metrics_and_text():
    day = DailyPnLSummary(
        date="2026-01-14",
        total_pnl=48.0,  # net
        gross_pnl=50.0,
        fees=2.0,
        trades_count=1,
        winning_trades=1,
        losing_trades=0,
        win_rate=100.0,
        avg_win=50.0,    # gross per trade
        avg_loss=0.0,
        largest_win=50.0,
        largest_loss=0.0,
        symbols_traded=["SPY"],
    )

    out = emit_daily_summary(day, thresholds=DailySummaryThresholds(flat_pnl_abs=10.0))

    assert out["label"] == "PROFITABLE"
    assert out["metrics"]["win_rate_pct"] == 100.0
    assert out["metrics"]["avg_win"] == 50.0
    assert out["metrics"]["avg_loss"] == 0.0
    assert "Expectancy" in out["text"]
    assert "Net P&L" in out["text"]

