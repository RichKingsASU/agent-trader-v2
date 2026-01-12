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


def out(msg: str = "") -> None:
    sys.stdout.write(str(msg) + "\n")


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
    out(char * length)


def print_portfolio_state() -> None:
    """Print current portfolio state."""
    out("\n📊 Portfolio State:")
    if not _portfolio_positions:
        out("  No open positions")
    else:
        for symbol, position in _portfolio_positions.items():
            out(f"  {symbol}:")
            out(f"    Delta: {position['delta']}")
            out(f"    Quantity: {position['quantity']}")
            out(f"    Price: {position['price']}")
    
    net_delta = _get_net_portfolio_delta()
    out(f"\n  Net Portfolio Delta: {net_delta}")
    out("")


def test_strategy_with_events(events_file: Path, set_negative_gex: bool = False) -> None:
    """
    Test the strategy with sample events.
    
    Args:
        events_file: Path to NDJSON events file
        set_negative_gex: If True, set GEX to negative value
    """
    print_separator()
    out("🎯 Testing 0DTE Gamma Scalper Strategy")
    print_separator()
    
    # Reset strategy state
    reset_strategy_state()
    
    # Optionally set negative GEX for testing
    if set_negative_gex:
        os.environ["GEX_VALUE"] = "-15000.0"
        out("⚠️  GEX set to NEGATIVE (-15000.0) - Tighter hedging threshold active")
    else:
        os.environ.pop("GEX_VALUE", None)
        out("✅ GEX not set - Using standard hedging threshold")
    
    out("")
    
    # Load events
    events = load_events(events_file)
    out(f"📥 Loaded {len(events)} market events\n")
    
    # Process each event
    for i, event in enumerate(events, 1):
        print_separator("-")
        out(f"Event {i}/{len(events)}: {event['symbol']} @ {event['ts']}")
        print_separator("-")
        
        # Display event payload
        payload = event.get("payload", {})
        out("\n📨 Event Payload:")
        if "delta" in payload:
            out(f"  Delta: {payload.get('delta')}")
            out(f"  Price: {payload.get('price')}")
            out(f"  Quantity: {payload.get('quantity', 1)}")
            out(f"  Underlying Price: {payload.get('underlying_price', 'N/A')}")
        else:
            out(f"  Price: {payload.get('price')}")
            out("  (Underlying asset - no delta)")
        
        # Process event
        out("\n⚙️  Processing event...")
        orders = on_market_event(event)
        
        # Display results
        if orders:
            out(f"\n✅ Generated {len(orders)} order(s):")
            for order in orders:
                out("\n  Order Intent:")
                out(f"    Intent ID: {order['intent_id']}")
                out(f"    Symbol: {order['symbol']}")
                out(f"    Side: {order['side'].upper()}")
                out(f"    Quantity: {order['qty']}")
                out(f"    Order Type: {order['order_type']}")
                out(f"    Client Tag: {order['client_tag']}")
                
                if "metadata" in order:
                    out("    Metadata:")
                    for key, value in order["metadata"].items():
                        out(f"      {key}: {value}")
        else:
            out("\n⏸️  No orders generated (delta within threshold or rate limited)")
        
        # Show portfolio state
        print_portfolio_state()
        
        out("")
    
    print_separator()
    out("✅ Strategy test complete!")
    print_separator()


def main() -> None:
    """Main test function."""
    events_file = Path(__file__).parent / "events.ndjson"
    
    if not events_file.exists():
        out(f"❌ Events file not found: {events_file}")
        return
    
    out("\n" + "=" * 80)
    out("TEST 1: Standard GEX (Positive/Neutral)")
    out("=" * 80 + "\n")
    test_strategy_with_events(events_file, set_negative_gex=False)
    
    out("\n" + "=" * 80)
    out("TEST 2: Negative GEX (High Volatility Regime)")
    out("=" * 80 + "\n")
    test_strategy_with_events(events_file, set_negative_gex=True)


if __name__ == "__main__":
    main()
