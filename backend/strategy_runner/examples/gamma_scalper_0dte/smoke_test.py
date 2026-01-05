"""
Quick smoke test to verify core strategy functionality
"""

from __future__ import annotations

import sys
from pathlib import Path
from decimal import Decimal

# Add strategy to path
sys.path.insert(0, str(Path(__file__).parent))

from strategy import (
    on_market_event,
    reset_strategy_state,
    _portfolio_positions,
    _get_net_portfolio_delta,
)


def test_basic_functionality():
    """Test basic strategy functionality."""
    print("🧪 Running Smoke Test for 0DTE Gamma Scalper Strategy\n")
    
    # Reset state
    reset_strategy_state()
    
    # Test 1: Position tracking
    print("Test 1: Position Tracking")
    event = {
        "protocol": "v1",
        "type": "market_event",
        "event_id": "evt_001",
        "ts": "2025-12-30T14:00:00Z",
        "symbol": "SPY_CALL",
        "source": "test",
        "payload": {
            "delta": 0.65,
            "price": 2.50,
            "quantity": 10,
            "underlying_price": 495.50,
        },
    }
    on_market_event(event)
    assert "SPY_CALL" in _portfolio_positions, "❌ Position not tracked"
    print("✅ Position tracking works")
    
    # Test 2: Net delta calculation
    print("\nTest 2: Net Delta Calculation")
    net_delta = _get_net_portfolio_delta()
    expected_delta = Decimal("6.50")
    assert net_delta == expected_delta, f"❌ Expected {expected_delta}, got {net_delta}"
    print(f"✅ Net delta calculated correctly: {net_delta}")
    
    # Test 3: Hedge order generation
    print("\nTest 3: Hedge Order Generation")
    reset_strategy_state()
    event["payload"]["underlying_price"] = 495.50
    orders = on_market_event(event)
    assert orders is not None and len(orders) > 0, "❌ No hedge orders generated"
    assert orders[0]["symbol"] == "SPY", "❌ Wrong hedge symbol"
    assert orders[0]["side"] == "sell", "❌ Wrong hedge side"
    print(f"✅ Hedge order generated: {orders[0]['side'].upper()} {orders[0]['qty']} {orders[0]['symbol']}")
    
    # Test 4: Market close exit
    print("\nTest 4: Market Close Exit")
    reset_strategy_state()
    _portfolio_positions["SPY_CALL"] = {
        "delta": Decimal("0.65"),
        "quantity": Decimal("10"),
        "price": Decimal("2.50"),
        "symbol": "SPY_CALL",
    }
    
    exit_event = {
        "protocol": "v1",
        "type": "market_event",
        "event_id": "evt_close",
        "ts": "2025-12-30T20:45:00Z",  # 3:45 PM ET
        "symbol": "SPY_CALL",
        "source": "test",
        "payload": {
            "delta": 0.65,
            "price": 2.50,
        },
    }
    
    exit_orders = on_market_event(exit_event)
    assert exit_orders is not None and len(exit_orders) > 0, "❌ No exit orders generated"
    assert exit_orders[0]["client_tag"] == "0dte_gamma_scalper_exit", "❌ Wrong order tag"
    assert "SPY_CALL" not in _portfolio_positions, "❌ Position not cleared"
    print(f"✅ Exit order generated at market close: {exit_orders[0]['side'].upper()} {exit_orders[0]['qty']} {exit_orders[0]['symbol']}")
    
    print("\n" + "="*60)
    print("✅ All smoke tests passed!")
    print("="*60)


if __name__ == "__main__":
    try:
        test_basic_functionality()
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
