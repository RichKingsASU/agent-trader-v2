#!/usr/bin/env python3
"""
Seed Whale Flow Test Data

This script populates Firestore with sample options flow data for testing
the WhaleFlowTracker component.

Usage:
    python scripts/seed_whale_flow_data.py --tenant-id YOUR_TENANT_ID
"""

import argparse
import random
from datetime import datetime, timedelta
from decimal import Decimal
from google.cloud import firestore

from backend.time.nyse_time import utc_now

# Sample symbols
SYMBOLS = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "MSFT", "AMZN", "GOOGL", "META"]

# Sample strikes (relative to underlying price)
STRIKE_OFFSETS = [-10, -7, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7, 10]

# Option types
OPTION_TYPES = ["call", "put"]

# Sides
SIDES = ["buy", "sell"]

# Execution sides
EXECUTION_SIDES = ["ask", "bid", "mid"]


def generate_random_trade(symbol: str, base_price: float) -> dict:
    """Generate a random options flow trade."""
    
    # Random strike
    strike_offset = random.choice(STRIKE_OFFSETS)
    strike = base_price + strike_offset
    
    # Random option type and side
    option_type = random.choice(OPTION_TYPES)
    side = random.choice(SIDES)
    
    # Weighted execution side (more likely at ask for buys)
    if side == "buy":
        execution_side = random.choices(
            EXECUTION_SIDES, 
            weights=[0.6, 0.2, 0.2]  # More aggressive buys
        )[0]
    else:
        execution_side = random.choices(
            EXECUTION_SIDES,
            weights=[0.2, 0.6, 0.2]  # More aggressive sells
        )[0]
    
    # Random size (contracts)
    size = random.randint(50, 2000)
    
    # Random premium per contract ($0.50 - $15.00)
    premium_per_contract = random.uniform(0.5, 15.0)
    total_premium = size * premium_per_contract * 100  # $100 per contract
    
    # Days to expiry (0-60 days)
    days_to_expiry = random.randint(0, 60)
    expiry_date = utc_now() + timedelta(days=days_to_expiry)
    expiry_str = expiry_date.strftime("%m/%d")
    
    # Calculate moneyness
    if option_type == "call":
        otm_percentage = ((strike - base_price) / base_price) * 100
        moneyness = "OTM" if strike > base_price else "ITM"
    else:
        otm_percentage = ((base_price - strike) / base_price) * 100
        moneyness = "OTM" if strike < base_price else "ITM"
    
    # ATM threshold
    if abs(otm_percentage) < 2:
        moneyness = "ATM"
    
    # Greeks (simplified)
    iv = random.uniform(0.15, 0.60)
    
    if option_type == "call":
        delta = random.uniform(0.2, 0.8) if moneyness != "OTM" else random.uniform(0.1, 0.4)
    else:
        delta = random.uniform(-0.8, -0.2) if moneyness != "OTM" else random.uniform(-0.4, -0.1)
    
    gamma = random.uniform(0.01, 0.05)
    
    # Sentiment
    if option_type == "call" and side == "buy":
        sentiment = "bullish"
    elif option_type == "put" and side == "buy":
        sentiment = "bearish"
    elif option_type == "call" and side == "sell":
        sentiment = "bearish"
    elif option_type == "put" and side == "sell":
        sentiment = "bullish"
    else:
        sentiment = "neutral"
    
    # Timestamp (recent trades)
    minutes_ago = random.randint(0, 60)
    timestamp = utc_now() - timedelta(minutes=minutes_ago)
    
    return {
        "symbol": symbol,
        "strike": round(strike, 2),
        "expiry": expiry_str,
        "expiry_date": expiry_date,
        "days_to_expiry": days_to_expiry,
        "option_type": option_type,
        "side": side,
        "execution_side": execution_side,
        "size": size,
        "premium": round(total_premium, 2),
        "underlying_price": round(base_price, 2),
        "iv": round(iv, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "moneyness": moneyness,
        "otm_percentage": round(otm_percentage, 2),
        "sentiment": sentiment,
        "timestamp": timestamp,
    }


def generate_golden_sweep(symbol: str, base_price: float) -> dict:
    """Generate a Golden Sweep trade (>$1M, <14 DTE)."""
    
    # Golden sweeps are typically aggressive
    option_type = random.choice(["call", "put"])
    side = "buy"
    execution_side = "ask"  # Always aggressive
    
    # Large size
    size = random.randint(1000, 5000)
    
    # High premium to exceed $1M
    premium_per_contract = random.uniform(10, 30)
    total_premium = size * premium_per_contract * 100
    
    # Less than 14 days to expiry
    days_to_expiry = random.randint(1, 13)
    expiry_date = utc_now() + timedelta(days=days_to_expiry)
    expiry_str = expiry_date.strftime("%m/%d")
    
    # Strike close to ATM for golden sweeps
    strike_offset = random.choice([-2, -1, 0, 1, 2])
    strike = base_price + strike_offset
    
    # Calculate moneyness
    if option_type == "call":
        otm_percentage = ((strike - base_price) / base_price) * 100
        moneyness = "OTM" if strike > base_price else "ITM"
    else:
        otm_percentage = ((base_price - strike) / base_price) * 100
        moneyness = "OTM" if strike < base_price else "ITM"
    
    if abs(otm_percentage) < 2:
        moneyness = "ATM"
    
    # Greeks
    iv = random.uniform(0.20, 0.45)
    delta = random.uniform(0.4, 0.7) if option_type == "call" else random.uniform(-0.7, -0.4)
    gamma = random.uniform(0.02, 0.06)
    
    # Sentiment (always directional for golden sweeps)
    sentiment = "bullish" if option_type == "call" else "bearish"
    
    # Recent timestamp
    minutes_ago = random.randint(0, 30)
    timestamp = utc_now() - timedelta(minutes=minutes_ago)
    
    return {
        "symbol": symbol,
        "strike": round(strike, 2),
        "expiry": expiry_str,
        "expiry_date": expiry_date,
        "days_to_expiry": days_to_expiry,
        "option_type": option_type,
        "side": side,
        "execution_side": execution_side,
        "size": size,
        "premium": round(total_premium, 2),
        "underlying_price": round(base_price, 2),
        "iv": round(iv, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "moneyness": moneyness,
        "otm_percentage": round(otm_percentage, 2),
        "sentiment": sentiment,
        "timestamp": timestamp,
    }


def seed_data(tenant_id: str, num_trades: int = 50, num_golden_sweeps: int = 5):
    """Seed Firestore with test options flow data."""
    
    print(f"🚀 Seeding Whale Flow data for tenant: {tenant_id}")
    print(f"📊 Generating {num_trades} regular trades + {num_golden_sweeps} golden sweeps")
    
    # Initialize Firestore
    db = firestore.Client()
    
    # Base prices for symbols
    base_prices = {
        "SPY": 432.50,
        "QQQ": 375.20,
        "IWM": 198.75,
        "AAPL": 178.50,
        "TSLA": 245.30,
        "NVDA": 495.60,
        "MSFT": 385.40,
        "AMZN": 155.80,
        "GOOGL": 138.90,
        "META": 465.20,
    }
    
    # Collection reference
    collection_ref = db.collection("tenants").document(tenant_id).collection(
        "market_intelligence"
    ).document("options_flow").collection("live")
    
    # Generate and write regular trades
    print("\n📝 Writing regular trades...")
    for i in range(num_trades):
        symbol = random.choice(SYMBOLS)
        base_price = base_prices[symbol]
        trade = generate_random_trade(symbol, base_price)
        
        doc_ref = collection_ref.document()
        doc_ref.set(trade)
        
        print(f"  ✓ {i+1}/{num_trades} - {symbol} ${trade['strike']} {trade['option_type'].upper()} "
              f"{trade['side'].upper()} {trade['size']} @ ${trade['premium']:,.0f}")
    
    # Generate and write golden sweeps
    print(f"\n👑 Writing {num_golden_sweeps} Golden Sweeps...")
    for i in range(num_golden_sweeps):
        symbol = random.choice(SYMBOLS)
        base_price = base_prices[symbol]
        trade = generate_golden_sweep(symbol, base_price)
        
        doc_ref = collection_ref.document()
        doc_ref.set(trade)
        
        print(f"  ✓ {i+1}/{num_golden_sweeps} - {symbol} ${trade['strike']} {trade['option_type'].upper()} "
              f"GOLDEN SWEEP {trade['size']} @ ${trade['premium']:,.0f}")
    
    # Seed system status for GEX overlay
    print("\n⚡ Writing system status (GEX data)...")
    ops_ref = db.collection("tenants").document(tenant_id).collection("ops").document("system_status")
    
    gex_status = {
        "net_gex": random.uniform(-5000000, 5000000),
        "volatility_bias": random.choice(["Bullish", "Bearish", "Neutral"]),
        "timestamp": utc_now(),
    }
    
    ops_ref.set(gex_status)
    print(f"  ✓ GEX: ${gex_status['net_gex']:,.0f} ({gex_status['volatility_bias']})")
    
    print(f"\n✅ Successfully seeded {num_trades + num_golden_sweeps} trades!")
    print(f"🎯 View in component: /whale-flow")


def main():
    parser = argparse.ArgumentParser(description="Seed Whale Flow test data")
    parser.add_argument(
        "--tenant-id",
        type=str,
        required=True,
        help="Tenant ID for data isolation"
    )
    parser.add_argument(
        "--num-trades",
        type=int,
        default=50,
        help="Number of regular trades to generate (default: 50)"
    )
    parser.add_argument(
        "--num-golden-sweeps",
        type=int,
        default=5,
        help="Number of golden sweeps to generate (default: 5)"
    )
    
    args = parser.parse_args()
    
    seed_data(
        tenant_id=args.tenant_id,
        num_trades=args.num_trades,
        num_golden_sweeps=args.num_golden_sweeps
    )


if __name__ == "__main__":
    main()
