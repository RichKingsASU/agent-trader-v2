#!/usr/bin/env python3
"""
Populate test data for Whale Flow Dashboard.

This script generates sample unusual options activity data and writes it to Firestore
at the path: marketData/options/unusual_activity

Usage:
    python scripts/populate_whale_flow_test_data.py
"""

import os
import sys
import random
from datetime import datetime, timedelta
from decimal import Decimal

# Add parent directory to path to import firebase_admin
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
from backend.persistence.firebase_client import require_firestore_emulator_or_allow_prod

# Sample tickers with varying activity levels
TICKERS = [
    "SPY", "QQQ", "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", 
    "META", "GOOGL", "AMD", "PLTR", "COIN", "SOFI", "RIVN"
]

# Option types
OPTION_TYPES = ["CALL", "PUT"]

# Trade types
TRADE_TYPES = ["SWEEP", "BLOCK"]

# Sentiments
SENTIMENTS = ["BULLISH", "BEARISH", "NEUTRAL"]

def generate_expiry_date():
    """Generate a random expiry date within the next 60 days."""
    days_ahead = random.choice([7, 14, 21, 30, 45, 60])
    expiry = datetime.now() + timedelta(days=days_ahead)
    return expiry.strftime("%Y-%m-%d")

def generate_whale_trade(ticker: str):
    """
    Generate a sample whale flow trade.
    
    Args:
        ticker: Stock symbol
        
    Returns:
        Dictionary with trade data
    """
    # Base price for ticker (simplified)
    base_prices = {
        "SPY": 580, "QQQ": 500, "AAPL": 230, "TSLA": 400, "NVDA": 140,
        "MSFT": 440, "AMZN": 220, "META": 600, "GOOGL": 180, "AMD": 120,
        "PLTR": 85, "COIN": 280, "SOFI": 15, "RIVN": 14
    }
    
    spot_price = base_prices.get(ticker, 100)
    
    # Random strike around spot price
    strike_offset = random.uniform(-0.1, 0.1)  # ±10%
    strike = round(spot_price * (1 + strike_offset), 2)
    
    # Trade type and sentiment correlation
    option_type = random.choice(OPTION_TYPES)
    trade_type = random.choice(TRADE_TYPES)
    
    # Correlate sentiment with option type for realism
    if option_type == "CALL":
        sentiment = random.choices(
            ["BULLISH", "BEARISH", "NEUTRAL"],
            weights=[60, 20, 20]
        )[0]
    else:
        sentiment = random.choices(
            ["BULLISH", "BEARISH", "NEUTRAL"],
            weights=[20, 60, 20]
        )[0]
    
    # Contract size (sweeps tend to be larger)
    if trade_type == "SWEEP":
        size = random.randint(100, 500) * 10
    else:
        size = random.randint(50, 200) * 10
    
    # Premium per contract (simplified calculation)
    if option_type == "CALL":
        premium_per_contract = random.uniform(2, 15) * 100
    else:
        premium_per_contract = random.uniform(1, 10) * 100
    
    total_premium = size * premium_per_contract
    
    # Implied volatility
    iv = random.uniform(0.20, 0.60)
    
    return {
        "ticker": ticker,
        "type": trade_type,
        "sentiment": sentiment,
        "option_type": option_type,
        "strike": f"{strike:.2f}",
        "expiry": generate_expiry_date(),
        "premium": f"{total_premium:.2f}",
        "size": size,
        "spot_price": f"{spot_price:.2f}",
        "implied_volatility": f"{iv:.4f}",
        "timestamp": SERVER_TIMESTAMP,
        "description": f"{trade_type} - {sentiment} {option_type} activity",
    }

def populate_test_data(num_trades: int = 30):
    """
    Populate Firestore with test whale flow data.
    
    Args:
        num_trades: Number of sample trades to generate
    """
    # Initialize Firebase Admin SDK
    if not firebase_admin._apps:
        # Try to use default credentials
        try:
            require_firestore_emulator_or_allow_prod(caller="scripts.populate_whale_flow_test_data.populate_test_data")
            firebase_admin.initialize_app()
            print("✅ Initialized Firebase Admin SDK with default credentials")
        except Exception as e:
            print(f"❌ Failed to initialize Firebase Admin SDK: {e}")
            print("\nMake sure you have:")
            print("1. Set GOOGLE_APPLICATION_CREDENTIALS environment variable")
            print("2. Or run 'gcloud auth application-default login'")
            sys.exit(1)
    
    db = firestore.client()
    collection_ref = db.collection("marketData").document("options").collection("unusual_activity")
    
    print(f"\n🐋 Generating {num_trades} whale flow trades...\n")
    
    # Generate trades with weighted ticker distribution
    # Some tickers should appear more frequently
    ticker_weights = {
        "SPY": 15, "QQQ": 10, "TSLA": 12, "NVDA": 10, "AAPL": 8,
        "MSFT": 6, "AMZN": 5, "META": 5, "GOOGL": 4, "AMD": 6,
        "PLTR": 4, "COIN": 4, "SOFI": 3, "RIVN": 3
    }
    
    ticker_pool = []
    for ticker, weight in ticker_weights.items():
        ticker_pool.extend([ticker] * weight)
    
    trades_added = 0
    for i in range(num_trades):
        ticker = random.choice(ticker_pool)
        trade = generate_whale_trade(ticker)
        
        try:
            doc_ref = collection_ref.add(trade)
            trades_added += 1
            
            # Print formatted output
            sentiment_emoji = {
                "BULLISH": "🟢",
                "BEARISH": "🔴",
                "NEUTRAL": "⚪"
            }
            
            print(f"{sentiment_emoji.get(trade['sentiment'], '⚪')} {trade['ticker']:6} "
                  f"{trade['type']:6} {trade['option_type']:4} "
                  f"${trade['strike']:>8} exp:{trade['expiry']} "
                  f"${float(trade['premium']):>12,.0f} premium "
                  f"({trade['size']:>6} contracts)")
            
        except Exception as e:
            print(f"❌ Failed to add trade {i+1}: {e}")
    
    print(f"\n✅ Successfully added {trades_added}/{num_trades} whale flow trades!")
    print(f"\n📊 View in Firestore:")
    print(f"   Collection: marketData/options/unusual_activity")
    print(f"\n🚀 Open your Whale Flow Dashboard to see the data!")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Populate whale flow test data")
    parser.add_argument(
        "--count",
        type=int,
        default=30,
        help="Number of trades to generate (default: 30)"
    )
    
    args = parser.parse_args()
    
    populate_test_data(args.count)
