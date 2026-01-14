"""Analytics module for trade performance analysis"""

from backend.analytics.trade_parser import (
    compute_daily_pnl,
    compute_trade_analytics,
    compute_win_loss_ratio,
    DailyPnLSummary,
    TradeAnalytics,
)
from backend.analytics.performance_interpretation import (
    DailySummaryThresholds,
    classify_day,
    compute_expectancy_per_trade,
    emit_daily_summary,
)

__all__ = [
    "compute_daily_pnl",
    "compute_trade_analytics",
    "compute_win_loss_ratio",
    "DailyPnLSummary",
    "TradeAnalytics",
    "DailySummaryThresholds",
    "classify_day",
    "compute_expectancy_per_trade",
    "emit_daily_summary",
]
