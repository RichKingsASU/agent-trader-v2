"""
Unit tests for 0DTE Gamma Scalper Strategy
"""

from __future__ import annotations

import os
import pytest
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

# Import strategy functions
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.strategy_runner.examples.gamma_scalper_0dte.strategy import (
    on_market_event,
    reset_strategy_state,
    _portfolio_positions,
    _hedge_position_qty,
    _get_net_portfolio_delta,
    _get_hedging_threshold,
    _calculate_hedge_quantity,
    _should_hedge,
    _is_market_close_time,
    _to_decimal,
    _parse_timestamp,
    HEDGING_THRESHOLD,
    HEDGING_THRESHOLD_NEGATIVE_GEX,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset strategy state before each test."""
    reset_strategy_state()
    os.environ.pop("GEX_VALUE", None)
    yield
    reset_strategy_state()


class TestDecimalConversion:
    """Test decimal conversion utilities."""
    
    def test_to_decimal_from_float(self):
        assert _to_decimal(1.5) == Decimal("1.5")
    
    def test_to_decimal_from_int(self):
        assert _to_decimal(10) == Decimal("10")
    
    def test_to_decimal_from_string(self):
        assert _to_decimal("0.65") == Decimal("0.65")
    
    def test_to_decimal_from_none(self):
        assert _to_decimal(None) == Decimal("0")
    
    def test_to_decimal_from_decimal(self):
        d = Decimal("3.14")
        assert _to_decimal(d) == d


class TestTimestampParsing:
    """Test timestamp parsing."""
    
    def test_parse_iso8601_with_z(self):
        ts = _parse_timestamp("2025-12-30T14:00:00Z")
        assert ts.tzinfo is not None
        assert ts.year == 2025
        assert ts.month == 12
        assert ts.day == 30
    
    def test_parse_iso8601_with_offset(self):
        ts = _parse_timestamp("2025-12-30T14:00:00-05:00")
        assert ts.tzinfo is not None
    
    def test_parse_empty_string(self):
        ts = _parse_timestamp("")
        assert ts.tzinfo is not None  # Should return current time with timezone


class TestMarketCloseTime:
    """Test market close time detection."""
    
    def test_before_close_time(self):
        # 2:00 PM ET
        dt = datetime(2025, 12, 30, 19, 0, 0, tzinfo=ZoneInfo("UTC"))  # 2 PM ET = 7 PM UTC
        assert not _is_market_close_time(dt)
    
    def test_at_close_time(self):
        # 3:45 PM ET exactly
        dt = datetime(2025, 12, 30, 20, 45, 0, tzinfo=ZoneInfo("UTC"))  # 3:45 PM ET = 8:45 PM UTC
        assert _is_market_close_time(dt)
    
    def test_after_close_time(self):
        # 4:00 PM ET
        dt = datetime(2025, 12, 30, 21, 0, 0, tzinfo=ZoneInfo("UTC"))  # 4 PM ET = 9 PM UTC
        assert _is_market_close_time(dt)


class TestPortfolioDelta:
    """Test net portfolio delta calculation."""
    
    def test_empty_portfolio(self):
        assert _get_net_portfolio_delta() == Decimal("0")
    
    def test_single_long_position(self):
        _portfolio_positions["SPY_CALL"] = {
            "delta": Decimal("0.65"),
            "quantity": Decimal("10"),
            "price": Decimal("2.50"),
        }
        # Net delta (shares) = 0.65 * 10 * 100 = 650
        assert _get_net_portfolio_delta() == Decimal("650.0")
    
    def test_single_short_position(self):
        _portfolio_positions["SPY_PUT"] = {
            "delta": Decimal("-0.35"),
            "quantity": Decimal("5"),
            "price": Decimal("1.75"),
        }
        # Net delta (shares) = -0.35 * 5 * 100 = -175
        assert _get_net_portfolio_delta() == Decimal("-175.00")
    
    def test_mixed_positions(self):
        _portfolio_positions["SPY_CALL"] = {
            "delta": Decimal("0.65"),
            "quantity": Decimal("10"),
            "price": Decimal("2.50"),
        }
        _portfolio_positions["SPY_PUT"] = {
            "delta": Decimal("-0.35"),
            "quantity": Decimal("5"),
            "price": Decimal("1.75"),
        }
        # Net delta (shares) = (0.65 * 10 * 100) + (-0.35 * 5 * 100) = 650 - 175 = 475
        assert _get_net_portfolio_delta() == Decimal("475.00")


class TestHedgingThreshold:
    """Test hedging threshold logic."""
    
    def test_standard_threshold_no_gex(self):
        threshold = _get_hedging_threshold()
        assert threshold == HEDGING_THRESHOLD
    
    def test_standard_threshold_positive_gex(self):
        os.environ["GEX_VALUE"] = "10000.0"
        threshold = _get_hedging_threshold()
        assert threshold == HEDGING_THRESHOLD
    
    def test_tighter_threshold_negative_gex(self):
        os.environ["GEX_VALUE"] = "-15000.0"
        threshold = _get_hedging_threshold()
        assert threshold == HEDGING_THRESHOLD_NEGATIVE_GEX
        assert threshold < HEDGING_THRESHOLD


class TestHedgeQuantity:
    """Test hedge quantity calculation."""
    
    def test_positive_delta_requires_sell(self):
        net_delta = Decimal("650")
        underlying_price = Decimal("495.50")
        hedge_qty = _calculate_hedge_quantity(net_delta, underlying_price)
        # Should be negative (sell) to offset positive delta
        assert hedge_qty == Decimal("-7")  # Rounded to nearest whole
    
    def test_negative_delta_requires_buy(self):
        net_delta = Decimal("-530")
        underlying_price = Decimal("495.50")
        hedge_qty = _calculate_hedge_quantity(net_delta, underlying_price)
        # Should be positive (buy) to offset negative delta
        assert hedge_qty == Decimal("530")  # Rounded to nearest whole share
    
    def test_zero_underlying_price(self):
        net_delta = Decimal("6.5")
        underlying_price = Decimal("0")
        hedge_qty = _calculate_hedge_quantity(net_delta, underlying_price)
        assert hedge_qty == Decimal("0")
    
    def test_rounding_half_up(self):
        # 0.655 delta for 1 contract => 65.5 shares; hedge should round half-up.
        net_delta = Decimal("65.5")
        underlying_price = Decimal("495.50")
        hedge_qty = _calculate_hedge_quantity(net_delta, underlying_price)
        # -6.5 should round to -7 with ROUND_HALF_UP
        assert hedge_qty == Decimal("-7")


class TestShouldHedge:
    """Test hedging decision logic."""
    
    def test_below_threshold_no_hedge(self):
        # 0.10 contract-delta => 10 shares (with 100x multiplier)
        net_delta = Decimal("10")
        current_time = datetime(2025, 12, 30, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert not _should_hedge(net_delta, current_time)
    
    def test_above_threshold_hedge(self):
        # 0.20 contract-delta => 20 shares
        net_delta = Decimal("20")
        current_time = datetime(2025, 12, 30, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert _should_hedge(net_delta, current_time)
    
    def test_negative_delta_above_threshold(self):
        net_delta = Decimal("-20")
        current_time = datetime(2025, 12, 30, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert _should_hedge(net_delta, current_time)
    
    def test_exactly_at_threshold_no_hedge(self):
        # 0.15 contract-delta => 15 shares
        net_delta = Decimal("15")
        current_time = datetime(2025, 12, 30, 19, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert not _should_hedge(net_delta, current_time)


class TestStrategyExecution:
    """Test strategy execution with market events."""
    
    def test_no_orders_for_non_option_event(self):
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_001",
            "ts": "2025-12-30T14:00:00Z",
            "symbol": "SPY",
            "source": "alpaca",
            "payload": {
                "price": 495.50,
                "bid": 495.48,
                "ask": 495.52,
            },
        }
        orders = on_market_event(event)
        assert orders == [] or orders is None
    
    def test_updates_position_with_option_event(self):
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_001",
            "ts": "2025-12-30T14:00:00Z",
            "symbol": "SPY_CALL",
            "source": "alpaca",
            "payload": {
                "delta": 0.65,
                "price": 2.50,
                "quantity": 10,
                "underlying_price": 495.50,
            },
        }
        on_market_event(event)
        assert "SPY_CALL" in _portfolio_positions
        assert _portfolio_positions["SPY_CALL"]["delta"] == Decimal("0.65")
    
    def test_generates_hedge_order_when_threshold_exceeded(self):
        # First event: establish position with high delta
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_001",
            "ts": "2025-12-30T14:00:00Z",
            "symbol": "SPY_CALL",
            "source": "alpaca",
            "payload": {
                "delta": 0.65,
                "price": 2.50,
                "quantity": 10,
                "underlying_price": 495.50,
            },
        }
        orders = on_market_event(event)
        
        # Should generate hedge order since net delta = 650 shares (6.5 contract-delta) > 0.15
        assert orders is not None
        assert len(orders) > 0
        
        hedge_order = orders[0]
        assert hedge_order["symbol"] == "SPY"
        assert hedge_order["side"] == "sell"  # Selling to offset positive delta
        assert hedge_order["qty"] == 650.0
        assert hedge_order["order_type"] == "market"
        assert hedge_order["client_tag"] == "0dte_gamma_scalper_hedge"
    
    def test_exits_all_positions_at_close_time(self):
        # Establish position
        _portfolio_positions["SPY_CALL"] = {
            "delta": Decimal("0.65"),
            "quantity": Decimal("10"),
            "price": Decimal("2.50"),
            "symbol": "SPY_CALL",
        }
        
        # Event at 3:45 PM ET (market close time)
        event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_close",
            "ts": "2025-12-30T20:45:00Z",  # 3:45 PM ET
            "symbol": "SPY_CALL",
            "source": "alpaca",
            "payload": {
                "delta": 0.65,
                "price": 2.50,
                "underlying_price": 495.50,
            },
        }
        
        orders = on_market_event(event)
        
        # Should generate exit order
        assert orders is not None
        assert len(orders) > 0
        
        exit_order = orders[0]
        assert exit_order["symbol"] == "SPY_CALL"
        assert exit_order["side"] == "sell"
        assert exit_order["client_tag"] == "0dte_gamma_scalper_exit"
        assert "market_close_exit" in exit_order["metadata"]["reason"]
        
        # Portfolio should be cleared
        assert "SPY_CALL" not in _portfolio_positions

    def test_flattens_spy_hedge_at_close_time_even_on_underlying_event(self):
        # Create a hedge by sending an option event that triggers hedging.
        option_event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_open",
            "ts": "2025-12-30T14:00:00Z",
            "symbol": "SPY_CALL",
            "source": "alpaca",
            "payload": {
                "delta": 0.65,
                "price": 2.50,
                "quantity": 10,
                "underlying_price": 495.50,
            },
        }
        orders = on_market_event(option_event)
        assert orders is not None and len(orders) > 0
        assert orders[0]["client_tag"] == "0dte_gamma_scalper_hedge"
        assert _hedge_position_qty["SPY"] != Decimal("0")

        # Trigger EOD logic using an underlying SPY event (no option greeks update).
        close_underlying_event = {
            "protocol": "v1",
            "type": "market_event",
            "event_id": "evt_close",
            "ts": "2025-12-30T20:45:00Z",  # 3:45 PM ET
            "symbol": "SPY",
            "source": "alpaca",
            "payload": {
                "price": 495.50,
                "bid": 495.48,
                "ask": 495.52,
            },
        }
        eod_orders = on_market_event(close_underlying_event)
        assert eod_orders is not None
        assert any(o.get("client_tag") == "0dte_gamma_scalper_hedge_flatten" for o in eod_orders)
        assert _hedge_position_qty["SPY"] == Decimal("0")

        # Subsequent events after close should not re-emit flatten intents.
        eod_orders_2 = on_market_event(close_underlying_event)
        assert eod_orders_2 == [] or eod_orders_2 is None


class TestGEXIntegration:
    """Test GEX-based adaptive hedging."""
    
    def test_negative_gex_uses_tighter_threshold(self):
        os.environ["GEX_VALUE"] = "-15000.0"

        # Net delta = 0.12 (between tighter and standard thresholds)
        # We assert the *decision* to hedge changes with GEX, independent of
        # share rounding/min-qty constraints in order generation.
        net_delta = Decimal("0.12")
        current_time = datetime(2025, 12, 30, 19, 0, 0, tzinfo=ZoneInfo("UTC"))

        assert _should_hedge(net_delta, current_time)

        # Without negative GEX, the standard 0.15 threshold would not hedge.
        reset_strategy_state()
        os.environ.pop("GEX_VALUE", None)
        assert not _should_hedge(net_delta, current_time)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
