"""
Congressional Alpha Tracker Strategy Package

A whale tracking alternative data strategy that copies trades from high-profile
politicians with demonstrated strong trading performance.
"""

from .strategy import (
    on_market_event,
    POLICY_WHALES,
    COMMITTEE_WEIGHTS,
    HIGH_CONVICTION_TICKERS,
    calculate_committee_weight,
    calculate_position_size,
    calculate_confidence,
    get_tracked_politicians,
    get_committee_tickers,
    is_high_conviction_ticker,
    get_politician_stats,
)

__all__ = [
    "on_market_event",
    "POLICY_WHALES",
    "COMMITTEE_WEIGHTS",
    "HIGH_CONVICTION_TICKERS",
    "calculate_committee_weight",
    "calculate_position_size",
    "calculate_confidence",
    "get_tracked_politicians",
    "get_committee_tickers",
    "is_high_conviction_ticker",
    "get_politician_stats",
]

__version__ = "1.0.0"
__author__ = "AgentTrader Core Team"
__description__ = "Congressional Alpha Tracker - Whale Tracking Strategy"
