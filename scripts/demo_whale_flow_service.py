#!/usr/bin/env python3
"""
Demo script for WhaleFlowService.

Shows how to:
1. Ingest whale flow data
2. Calculate conviction scores
3. Query recent conviction for Maestro integration

Usage:
    python scripts/demo_whale_flow_service.py
"""

import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.whale_flow import WhaleFlowService, get_recent_conviction
from backend.persistence.firebase_client import get_firestore_client


def demo_ingestion():
    """Demo: Ingest sample whale flow data."""
    print("\n" + "="*70)
    print("DEMO 1: Ingesting Whale Flow Data")
    print("="*70)
    
    service = WhaleFlowService()
    
    # Sample flow data from a provider
    sample_flows = [
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "underlying_symbol": "SPY",
            "option_symbol": "SPY251219C00580000",
            "side": "buy",
            "size": 250,
            "premium": 62500.00,  # $250 per contract * 250 = $62,500
            "strike_price": 580.00,
            "expiration_date": "2025-12-19",
            "option_type": "call",
            "trade_price": 2.50,
            "bid_price": 2.45,
            "ask_price": 2.50,  # Trade at ask = aggressive
            "spot_price": 575.00,
            "implied_volatility": 0.18,
            "open_interest": 1000,
            "volume": 1500,
            "exchange": "CBOE",
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "underlying_symbol": "AAPL",
            "option_symbol": "AAPL251219P00230000",
            "side": "buy",
            "size": 150,
            "premium": 22500.00,
            "strike_price": 230.00,
            "expiration_date": "2025-12-19",
            "option_type": "put",
            "trade_price": 1.50,
            "bid_price": 1.45,
            "ask_price": 1.55,
            "spot_price": 235.00,
            "implied_volatility": 0.22,
            "open_interest": 800,
            "volume": 300,
            "exchange": "CBOE",
        },
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "underlying_symbol": "TSLA",
            "option_symbol": "TSLA251219C00420000",
            "side": "buy",
            "size": 500,  # Large block
            "premium": 200000.00,
            "strike_price": 420.00,
            "expiration_date": "2025-12-19",
            "option_type": "call",
            "trade_price": 4.00,
            "bid_price": 3.95,
            "ask_price": 4.05,
            "spot_price": 410.00,
            "implied_volatility": 0.45,
            "open_interest": 2000,
            "volume": 3000,
            "exchange": "CBOE",
        },
    ]
    
    # Ingest flows for a sample user
    uid = "demo_user_123"
    
    print(f"\nIngesting {len(sample_flows)} flows for user: {uid}\n")
    
    for i, flow in enumerate(sample_flows, 1):
        # Map to schema and show details
        mapped = service.map_flow_to_schema(uid, flow, source="demo_provider")
        
        print(f"Flow #{i}: {mapped['underlying_symbol']}")
        print(f"  Type:       {mapped['flow_type']}")
        print(f"  Sentiment:  {mapped['sentiment']}")
        print(f"  Size:       {mapped['size']} contracts")
        print(f"  Premium:    ${mapped['premium']}")
        print(f"  OTM:        {mapped['is_otm']}")
        print(f"  Vol/OI:     {mapped['vol_oi_ratio']}")
        print(f"  Conviction: {mapped['conviction_score']}")
        print()
    
    # Batch ingest (in production)
    try:
        doc_ids = service.ingest_batch(uid, sample_flows, source="demo_provider")
        print(f"✅ Successfully ingested {len(doc_ids)} flows!")
        print(f"   Document IDs: {doc_ids[:3]}..." if len(doc_ids) > 3 else f"   Document IDs: {doc_ids}")
    except Exception as e:
        print(f"⚠️  Ingestion skipped (demo mode): {e}")


def demo_conviction_scoring():
    """Demo: Calculate conviction scores for different scenarios."""
    print("\n" + "="*70)
    print("DEMO 2: Conviction Scoring")
    print("="*70)
    
    service = WhaleFlowService()
    
    scenarios = [
        {
            "name": "SWEEP at ask, OTM, high vol/OI",
            "data": {
                "flow_type": "SWEEP",
                "is_otm": True,
                "vol_oi_ratio": "2.5",
            },
            "expected": "1.00 (maximum conviction)",
        },
        {
            "name": "BLOCK trade, at-the-money",
            "data": {
                "flow_type": "BLOCK",
                "is_otm": False,
                "vol_oi_ratio": "0.8",
            },
            "expected": "0.50 (base BLOCK score)",
        },
        {
            "name": "SWEEP, ITM, normal vol/OI",
            "data": {
                "flow_type": "SWEEP",
                "is_otm": False,
                "vol_oi_ratio": "1.0",
            },
            "expected": "0.80 (base SWEEP score)",
        },
        {
            "name": "BLOCK, OTM, high vol/OI",
            "data": {
                "flow_type": "BLOCK",
                "is_otm": True,
                "vol_oi_ratio": "1.5",
            },
            "expected": "0.70 (BLOCK + OTM + vol/OI boost)",
        },
    ]
    
    print("\nScoring different flow scenarios:\n")
    
    for scenario in scenarios:
        score = service.calculate_conviction_score(scenario["data"])
        print(f"Scenario: {scenario['name']}")
        print(f"  Score:    {score}")
        print(f"  Expected: {scenario['expected']}")
        print()


def demo_maestro_integration():
    """Demo: Maestro checking recent conviction before placing trade."""
    print("\n" + "="*70)
    print("DEMO 3: Maestro Integration - Trade Validation")
    print("="*70)
    
    # Simulate Maestro considering a trade
    print("\n📊 Maestro is considering a trade:")
    print("   Ticker: AAPL")
    print("   Direction: LONG (bullish)")
    print("   Strategy: Momentum breakout")
    print()
    
    # Check for recent whale activity
    uid = "demo_user_123"
    ticker = "AAPL"
    
    print(f"🔍 Checking recent whale activity for {ticker}...")
    
    try:
        conviction = get_recent_conviction(uid, ticker, lookback_minutes=30)
        
        print(f"\n📈 Whale Flow Analysis (last 30 minutes):")
        print(f"   Activity detected: {conviction['has_activity']}")
        
        if conviction['has_activity']:
            print(f"   Total flows:       {conviction['total_flows']}")
            print(f"   Avg conviction:    {conviction['avg_conviction']}")
            print(f"   Max conviction:    {conviction['max_conviction']}")
            print(f"   Bullish flows:     {conviction['bullish_flows']}")
            print(f"   Bearish flows:     {conviction['bearish_flows']}")
            print(f"   Total premium:     ${conviction['total_premium']:,.2f}")
            print(f"   Dominant sentiment: {conviction['dominant_sentiment']}")
            print()
            
            # Maestro decision logic
            if conviction['dominant_sentiment'] == 'BULLISH' and conviction['avg_conviction'] > Decimal("0.7"):
                print("✅ TRADE APPROVED: Whale activity aligns with bullish strategy!")
                print("   High conviction bullish flows detected.")
            elif conviction['dominant_sentiment'] == 'BEARISH':
                print("⚠️  TRADE CAUTION: Whale activity is bearish, conflicts with bullish strategy!")
                print("   Consider reducing position size or waiting.")
            else:
                print("ℹ️  TRADE PROCEED: No strong whale signal, proceed with base strategy.")
        else:
            print("   No recent whale activity detected.")
            print("ℹ️  TRADE PROCEED: No whale signal, proceed with base strategy.")
        
    except Exception as e:
        print(f"⚠️  Query skipped (demo mode): {e}")
        print("ℹ️  In production, Maestro would fetch real data from Firestore.")


def demo_code_examples():
    """Demo: Show code examples for developers."""
    print("\n" + "="*70)
    print("DEMO 4: Code Examples for Developers")
    print("="*70)
    
    print("""
# Example 1: Simple ingestion in your data pipeline
from backend.services.whale_flow import WhaleFlowService

service = WhaleFlowService()
flow_data = {
    "timestamp": "2025-12-30T12:00:00Z",
    "underlying_symbol": "SPY",
    "option_symbol": "SPY251219C00580000",
    "side": "buy",
    "size": 100,
    "premium": 10000,
    # ... other fields
}
doc_id = service.ingest_flow("user123", flow_data)


# Example 2: Batch ingestion for performance
flows = [flow1, flow2, flow3]  # List of flow dictionaries
doc_ids = service.ingest_batch("user123", flows)


# Example 3: Maestro integration (most common use case)
from backend.services.whale_flow import get_recent_conviction

# In your strategy logic:
def should_enter_trade(ticker, direction):
    conviction = get_recent_conviction(
        uid="user123",
        ticker=ticker,
        lookback_minutes=30
    )
    
    if conviction['has_activity']:
        if direction == 'LONG' and conviction['dominant_sentiment'] == 'BULLISH':
            if conviction['avg_conviction'] > Decimal("0.7"):
                return True, "Strong bullish whale activity"
        elif direction == 'SHORT' and conviction['dominant_sentiment'] == 'BEARISH':
            if conviction['avg_conviction'] > Decimal("0.7"):
                return True, "Strong bearish whale activity"
    
    return False, "No strong whale signal"


# Example 4: Custom conviction analysis
service = WhaleFlowService()
flow_mapped = service.map_flow_to_schema(uid, raw_flow_data)
conviction_score = service.calculate_conviction_score(flow_mapped)

if conviction_score > Decimal("0.8"):
    alert_user("High conviction whale flow detected!")
""")


def main():
    """Run all demos."""
    print("\n" + "="*70)
    print("🐋 Whale Flow Service Demo")
    print("="*70)
    print("\nThis demo shows how to use the WhaleFlowService for:")
    print("  1. Ingesting options flow data")
    print("  2. Calculating conviction scores")
    print("  3. Maestro trade validation")
    print("  4. Code examples")
    
    try:
        demo_ingestion()
        demo_conviction_scoring()
        demo_maestro_integration()
        demo_code_examples()
        
        print("\n" + "="*70)
        print("✅ Demo completed!")
        print("="*70)
        print("\n📚 Next steps:")
        print("   1. Review the service code: backend/services/whale_flow.py")
        print("   2. Run tests: pytest tests/test_whale_flow_service.py")
        print("   3. Integrate with your data pipeline")
        print("   4. Use get_recent_conviction() in Maestro strategies")
        print()
        
    except Exception as e:
        print(f"\n❌ Demo error: {e}")
        print("\nNote: This demo may fail if Firebase is not configured.")
        print("To run fully, ensure GOOGLE_APPLICATION_CREDENTIALS is set.")


if __name__ == "__main__":
    main()
