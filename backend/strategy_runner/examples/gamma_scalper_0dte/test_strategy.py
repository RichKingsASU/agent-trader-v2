"""
Test script for 0DTE Gamma Scalper Strategy

This script demonstrates the strategy behavior with sample market events.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add strategy module to path
strategy_dir = Path(__file__).parent
sys.path.insert(0, str(strategy_dir))

from strategy import (
    on_market_event,
    reset_strategy_state,
    _portfolio_positions,
    _get_net_portfolio_delta,
)


def load_events(events_file: Path) -> List[Dict[str, Any]]:
    """Load NDJSON events from file."""
    events = []
    with open(events_file, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def print_separator(char: str = "=", length: int = 80) -> None:
    """Print a separator line."""
    print(char * length)


def print_portfolio_state() -> None:
    """Print current portfolio state."""
    print("\n📊 Portfolio State:")
    if not _portfolio_positions:
        print("  No open positions")
    else:
        for symbol, position in _portfolio_positions.items():
            print(f"  {symbol}:")
            print(f"    Delta: {position['delta']}")
            print(f"    Quantity: {position['quantity']}")
            print(f"    Price: {position['price']}")
    
    net_delta = _get_net_portfolio_delta()
    print(f"\n  Net Portfolio Delta: {net_delta}")
    print()


def test_strategy_with_events(events_file: Path, set_negative_gex: bool = False) -> None:
    """
    Test the strategy with sample events.
    
    Args:
        events_file: Path to NDJSON events file
        set_negative_gex: If True, set GEX to negative value
    """
    print_separator()
    print("🎯 Testing 0DTE Gamma Scalper Strategy")
    print_separator()
    
    # Reset strategy state
    reset_strategy_state()
    
    # Optionally set negative GEX for testing
    if set_negative_gex:
        os.environ["GEX_VALUE"] = "-15000.0"
        print("⚠️  GEX set to NEGATIVE (-15000.0) - Tighter hedging threshold active")
    else:
        os.environ.pop("GEX_VALUE", None)
        print("✅ GEX not set - Using standard hedging threshold")
    
    print()
    
    # Load events
    events = load_events(events_file)
    print(f"📥 Loaded {len(events)} market events\n")
    
    # Process each event
    for i, event in enumerate(events, 1):
        print_separator("-")
        print(f"Event {i}/{len(events)}: {event['symbol']} @ {event['ts']}")
        print_separator("-")
        
        # Display event payload
        payload = event.get("payload", {})
        print("\n📨 Event Payload:")
        if "delta" in payload:
            print(f"  Delta: {payload.get('delta')}")
            print(f"  Price: {payload.get('price')}")
            print(f"  Quantity: {payload.get('quantity', 1)}")
            print(f"  Underlying Price: {payload.get('underlying_price', 'N/A')}")
        else:
            print(f"  Price: {payload.get('price')}")
            print(f"  (Underlying asset - no delta)")
        
        # Process event
        print("\n⚙️  Processing event...")
        orders = on_market_event(event)
        
        # Display results
        if orders:
            print(f"\n✅ Generated {len(orders)} order(s):")
            for order in orders:
                print(f"\n  Order Intent:")
                print(f"    Intent ID: {order['intent_id']}")
                print(f"    Symbol: {order['symbol']}")
                print(f"    Side: {order['side'].upper()}")
                print(f"    Quantity: {order['qty']}")
                print(f"    Order Type: {order['order_type']}")
                print(f"    Client Tag: {order['client_tag']}")
                
                if "metadata" in order:
                    print(f"    Metadata:")
                    for key, value in order["metadata"].items():
                        print(f"      {key}: {value}")
        else:
            print("\n⏸️  No orders generated (delta within threshold or rate limited)")
        
        # Show portfolio state
        print_portfolio_state()
        
        print()
    
    print_separator()
    print("✅ Strategy test complete!")
    print_separator()


def main() -> None:
    """Main test function."""
    events_file = Path(__file__).parent / "events.ndjson"
    
    if not events_file.exists():
        print(f"❌ Events file not found: {events_file}")
        return
    
    print("\n" + "=" * 80)
    print("TEST 1: Standard GEX (Positive/Neutral)")
    print("=" * 80 + "\n")
    test_strategy_with_events(events_file, set_negative_gex=False)
    
    print("\n" + "=" * 80)
    print("TEST 2: Negative GEX (High Volatility Regime)")
    print("=" * 80 + "\n")
    test_strategy_with_events(events_file, set_negative_gex=True)


if __name__ == "__main__":
    main()
