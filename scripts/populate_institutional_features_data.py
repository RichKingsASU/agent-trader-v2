#!/usr/bin/env python3
"""
Populate Sample Data for Institutional Features

This script creates sample data for all four institutional features:
1. Whale Flow (unusual options activity)
2. Sentiment Heatmap (sector sentiment scores)
3. Shadow Trades (for journal testing)
4. Market Regime (GEX data for risk breakers)

Usage:
    python scripts/populate_institutional_features_data.py

Requirements:
    - firebase-admin
    - Firestore database initialized
    - Service account credentials configured
"""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.lib.exec_guard as exec_guard

import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, timedelta
import random
from typing import List, Dict, Any


def initialize_firebase():
    """Initialize Firebase Admin SDK."""
    if not firebase_admin._apps:
        # Use default credentials or specify path
        # cred = credentials.Certificate('path/to/serviceAccountKey.json')
        firebase_admin.initialize_app()
    
    return firestore.client()


def populate_whale_flow_data(db: firestore.Client):
    """
    Populate unusual options activity data for Whale Flow Dashboard.
    """
    print("📊 Populating Whale Flow data...")
    
    unusual_activity_ref = db.collection("marketData").document("options").collection("unusual_activity")
    
    # Sample tickers and activities
    samples = [
        {
            "ticker": "SPY",
            "type": "Sweep",
            "premium": "2500000",  # $2.5M
            "strike": "450",
            "expiry": "2025-12-31",
            "optionType": "Call",
            "side": "Ask",
            "volume": 1000,
            "spotPrice": "445.50",
            "impliedVolatility": 0.18,
        },
        {
            "ticker": "QQQ",
            "type": "Block",
            "premium": "1800000",  # $1.8M
            "strike": "380",
            "expiry": "2025-12-31",
            "optionType": "Put",
            "side": "Ask",
            "volume": 800,
            "spotPrice": "385.25",
            "impliedVolatility": 0.22,
        },
        {
            "ticker": "AAPL",
            "type": "Sweep",
            "premium": "850000",  # $850K
            "strike": "180",
            "expiry": "2025-01-17",
            "optionType": "Call",
            "side": "Ask",
            "volume": 500,
            "spotPrice": "178.50",
            "impliedVolatility": 0.25,
        },
        {
            "ticker": "TSLA",
            "type": "Sweep",
            "premium": "3200000",  # $3.2M
            "strike": "250",
            "expiry": "2025-01-17",
            "optionType": "Call",
            "side": "Bid",
            "volume": 1200,
            "spotPrice": "248.75",
            "impliedVolatility": 0.55,
        },
        {
            "ticker": "NVDA",
            "type": "Block",
            "premium": "4500000",  # $4.5M
            "strike": "500",
            "expiry": "2025-02-21",
            "optionType": "Call",
            "side": "Ask",
            "volume": 1500,
            "spotPrice": "495.00",
            "impliedVolatility": 0.40,
        },
    ]
    
    # Add timestamps (recent activities)
    base_time = datetime.now()
    for i, activity in enumerate(samples):
        activity["timestamp"] = base_time - timedelta(minutes=i * 5)
        activity["metadata"] = {
            "source": "test_data",
            "confidence": random.uniform(0.7, 0.95),
        }
        
        doc_ref = unusual_activity_ref.add(activity)
        print(f"  ✓ Added {activity['ticker']} {activity['type']} activity")
    
    print(f"✅ Added {len(samples)} whale flow activities\n")


def populate_sentiment_data(db: firestore.Client):
    """
    Populate sector sentiment data for Sentiment Heatmap.
    """
    print("🎨 Populating Sentiment Heatmap data...")
    
    sentiment_ref = db.collection("marketData").document("sentiment").collection("sectors")
    
    # Top stocks by sector with realistic market caps
    samples = [
        # Technology
        {"symbol": "AAPL", "sector": "Technology", "marketCap": 3000, "sentimentScore": 0.82},
        {"symbol": "MSFT", "sector": "Technology", "marketCap": 2800, "sentimentScore": 0.75},
        {"symbol": "NVDA", "sector": "Technology", "marketCap": 2200, "sentimentScore": 0.88},
        {"symbol": "GOOGL", "sector": "Technology", "marketCap": 1700, "sentimentScore": 0.65},
        {"symbol": "META", "sector": "Technology", "marketCap": 1200, "sentimentScore": 0.55},
        {"symbol": "TSLA", "sector": "Technology", "marketCap": 800, "sentimentScore": 0.45},
        {"symbol": "AMD", "sector": "Technology", "marketCap": 250, "sentimentScore": 0.70},
        
        # Financial
        {"symbol": "JPM", "sector": "Financial", "marketCap": 500, "sentimentScore": 0.35},
        {"symbol": "BAC", "sector": "Financial", "marketCap": 320, "sentimentScore": 0.25},
        {"symbol": "WFC", "sector": "Financial", "marketCap": 180, "sentimentScore": 0.15},
        
        # Healthcare
        {"symbol": "JNJ", "sector": "Healthcare", "marketCap": 380, "sentimentScore": 0.50},
        {"symbol": "UNH", "sector": "Healthcare", "marketCap": 520, "sentimentScore": 0.60},
        {"symbol": "PFE", "sector": "Healthcare", "marketCap": 150, "sentimentScore": -0.20},
        
        # Consumer
        {"symbol": "AMZN", "sector": "Consumer", "marketCap": 1500, "sentimentScore": 0.78},
        {"symbol": "WMT", "sector": "Consumer", "marketCap": 420, "sentimentScore": 0.40},
        {"symbol": "HD", "sector": "Consumer", "marketCap": 350, "sentimentScore": 0.30},
        
        # Energy
        {"symbol": "XOM", "sector": "Energy", "marketCap": 450, "sentimentScore": -0.35},
        {"symbol": "CVX", "sector": "Energy", "marketCap": 280, "sentimentScore": -0.25},
        
        # ETFs
        {"symbol": "SPY", "sector": "ETF", "marketCap": 500, "sentimentScore": 0.60},
        {"symbol": "QQQ", "sector": "ETF", "marketCap": 250, "sentimentScore": 0.72},
    ]
    
    for stock in samples:
        stock["change24h"] = random.uniform(-3, 5)
        stock["volume"] = int(random.uniform(50_000_000, 200_000_000))
        stock["aiSummary"] = generate_ai_summary(stock["symbol"], stock["sentimentScore"])
        stock["timestamp"] = firestore.SERVER_TIMESTAMP
        
        sentiment_ref.document(stock["symbol"]).set(stock)
        print(f"  ✓ Added {stock['symbol']} ({stock['sector']}): {stock['sentimentScore']:.2f}")
    
    print(f"✅ Added {len(samples)} sentiment scores\n")


def generate_ai_summary(symbol: str, score: float) -> str:
    """Generate a simple AI summary based on sentiment score."""
    if score > 0.7:
        return f"{symbol} shows strong bullish momentum with high investor confidence."
    elif score > 0.3:
        return f"{symbol} exhibits positive sentiment with moderate upside potential."
    elif score > -0.3:
        return f"{symbol} displays neutral sentiment with mixed signals."
    elif score > -0.7:
        return f"{symbol} faces bearish pressure with declining investor interest."
    else:
        return f"{symbol} shows very bearish sentiment with significant downside risk."


def populate_market_regime(db: firestore.Client):
    """
    Populate market regime data for Risk Circuit Breakers.
    """
    print("🌐 Populating Market Regime data...")
    
    regime_ref = db.collection("systemStatus").document("market_regime")
    
    regime_data = {
        "timestamp": firestore.SERVER_TIMESTAMP,
        "spy": {
            "net_gex": "1500000000.00",  # $1.5B positive GEX
            "volatility_bias": "Bullish",
            "spot_price": "445.50",
            "option_count": 1250,
            "total_call_gex": "2000000000.00",
            "total_put_gex": "500000000.00",
        },
        "qqq": {
            "net_gex": "800000000.00",  # $800M positive GEX
            "volatility_bias": "Bullish",
            "spot_price": "385.25",
            "option_count": 980,
            "total_call_gex": "1200000000.00",
            "total_put_gex": "400000000.00",
        },
        "market_volatility_bias": "Bullish",
        "regime": "LONG_GAMMA",
        "vix": 18.5,  # Normal VIX level
        "last_updated": datetime.now().isoformat(),
    }
    
    regime_ref.set(regime_data, merge=True)
    print(f"  ✓ Set market regime: {regime_data['regime']} (VIX: {regime_data['vix']})")
    print(f"✅ Market regime data updated\n")


def populate_sample_shadow_trades(db: firestore.Client, user_id: str = "test_user_123"):
    """
    Populate sample shadow trades for testing Trading Journal.
    
    Note: These will be CLOSED to trigger the journal function.
    """
    print("📈 Populating Sample Shadow Trades...")
    
    shadow_trades_ref = db.collection("shadowTradeHistory")
    
    # Sample trades with different outcomes
    base_time = datetime.now()
    
    samples = [
        {
            "uid": user_id,
            "symbol": "SPY",
            "side": "BUY",
            "quantity": 10,
            "entry_price": "440.00",
            "exit_price": "445.50",
            "realized_pnl": "55.00",  # Profitable
            "allocation": 0.3,
            "reasoning": "Bullish GEX regime, positive momentum",
            "status": "CLOSED",
            "created_at": base_time - timedelta(hours=4),
            "closed_at": base_time - timedelta(hours=2),
            "exit_reason": "Take profit",
        },
        {
            "uid": user_id,
            "symbol": "AAPL",
            "side": "BUY",
            "quantity": 15,
            "entry_price": "180.00",
            "exit_price": "178.50",
            "realized_pnl": "-22.50",  # Loss
            "allocation": 0.25,
            "reasoning": "Tech sector rotation expected",
            "status": "CLOSED",
            "created_at": base_time - timedelta(hours=6),
            "closed_at": base_time - timedelta(hours=3),
            "exit_reason": "Stop loss triggered",
        },
        {
            "uid": user_id,
            "symbol": "TSLA",
            "side": "BUY",
            "quantity": 5,
            "entry_price": "245.00",
            "exit_price": "248.75",
            "realized_pnl": "18.75",  # Small profit
            "allocation": 0.15,
            "reasoning": "Oversold RSI, potential bounce",
            "status": "CLOSED",
            "created_at": base_time - timedelta(hours=8),
            "closed_at": base_time - timedelta(hours=5),
            "exit_reason": "Time-based exit",
        },
    ]
    
    for trade in samples:
        doc_ref = shadow_trades_ref.add(trade)
        trade_id = doc_ref[1].id
        print(f"  ✓ Added {trade['symbol']} trade: P&L ${trade['realized_pnl']}")
        print(f"    (Trade ID: {trade_id} - will trigger journal analysis)")
    
    print(f"✅ Added {len(samples)} shadow trades\n")
    print(f"⚠️  Note: Check Cloud Function logs for journal analysis:\n")
    print(f"    firebase functions:log --only on_trade_closed\n")


def main():
    """Main function to populate all institutional feature data."""
    print("=" * 60)
    print("🚀 Populating Institutional Features Sample Data")
    print("=" * 60)
    print()
    
    try:
        db = initialize_firebase()
        print("✅ Firebase initialized\n")
        
        # Populate all features
        populate_whale_flow_data(db)
        populate_sentiment_data(db)
        populate_market_regime(db)
        
        # Optional: populate shadow trades (requires user_id)
        user_id = input("Enter user ID for shadow trades (or press Enter to skip): ").strip()
        if user_id:
            populate_sample_shadow_trades(db, user_id)
        else:
            print("⏭️  Skipped shadow trades (no user ID provided)\n")
        
        print("=" * 60)
        print("✅ All sample data populated successfully!")
        print("=" * 60)
        print()
        print("Next steps:")
        print("1. Deploy Cloud Functions: firebase deploy --only functions")
        print("2. Deploy frontend: firebase deploy --only hosting")
        print("3. Test each feature in the UI")
        print("4. Check Cloud Function logs for journal analysis")
        print()
        print("🎉 You're ready to test the institutional features!")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exec_guard.enforce_execution_policy(__file__, sys.argv)
    exit(main())
