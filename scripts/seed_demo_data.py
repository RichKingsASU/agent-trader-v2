#!/usr/bin/env python3
"""
Seed demo data for E2E testing.

Creates a demo tenant with sample market data and account snapshots
to enable testing of the frontend UI without requiring backend services.

USAGE:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
    export FIREBASE_PROJECT_ID=agenttrader-dev
    python3 scripts/seed_demo_data.py

CREATED DATA:
    - Tenant: demo_tenant
    - User: demo_user (uid = local)
    - Market data: SPY, QQQ, AAPL (6 1-min bars each)
    - Account snapshot: $100k equity
    - Sample trades: 2 demo trades
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, Any, List

try:
    from firebase_admin import initialize_app, credentials, firestore, auth
except ImportError:
    print("ERROR: firebase-admin not installed. Run: pip install firebase-admin")
    sys.exit(1)


def init_firebase():
    """Initialize Firebase Admin SDK."""
    project_id = os.getenv("FIREBASE_PROJECT_ID", "agenttrader-dev")

    try:
        app = initialize_app(
            credentials.ApplicationDefault(),
            {"projectId": project_id}
        )
    except Exception as e:
        print(f"ERROR: Failed to initialize Firebase: {e}")
        sys.exit(1)

    return firestore.client(), project_id


def seed_tenant(db: firestore.Client, tenant_id: str = "demo_tenant") -> None:
    """Create demo tenant document."""
    print(f"[TENANT] Creating tenant: {tenant_id}")

    tenant_ref = db.collection("tenants").document(tenant_id)
    tenant_ref.set({
        "tenant_id": tenant_id,
        "display_name": "Demo Tenant",
        "environment": "demo",
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    print(f"[TENANT] ✓ Created {tenant_id}")


def seed_user(db: firestore.Client, tenant_id: str, uid: str = "local", email: str = "local@example.com") -> None:
    """Create demo user in tenant."""
    print(f"[USER] Creating user: {uid} in tenant {tenant_id}")

    user_ref = db.collection("tenants").document(tenant_id).collection("users").document(uid)
    user_ref.set({
        "uid": uid,
        "email": email,
        "display_name": "Demo User",
        "role": "operator",
        "created_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    print(f"[USER] ✓ Created {uid}")


def seed_market_data(db: firestore.Client, tenant_id: str) -> None:
    """Create sample market data (1-min bars) for watchlist sparklines."""
    print(f"[MARKET_DATA] Creating market data bars")

    symbols = ["SPY", "QQQ", "AAPL"]
    base_prices = {"SPY": 430.00, "QQQ": 368.00, "AAPL": 178.00}

    now = datetime.utcnow()
    market_data_ref = db.collection("tenants").document(tenant_id).collection("market_data_1m")

    for symbol in symbols:
        base_price = base_prices[symbol]

        # Create 6 1-min bars going backwards in time
        for i in range(6):
            ts = now - timedelta(minutes=i)
            price_variation = (i * 0.15) - 0.45  # Small price movement

            doc_id = f"{symbol}_{ts.strftime('%Y%m%d_%H%M%S')}"
            market_data_ref.document(doc_id).set({
                "symbol": symbol,
                "open": base_price + price_variation,
                "high": base_price + price_variation + 0.25,
                "low": base_price + price_variation - 0.25,
                "close": base_price + price_variation + 0.1,
                "volume": 1000000 + (i * 50000),
                "ts": ts,
                "created_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)

        print(f"[MARKET_DATA] ✓ Created 6 bars for {symbol}")


def seed_account_data(db: firestore.Client, uid: str = "local") -> None:
    """Create sample account snapshot for user."""
    print(f"[ACCOUNT] Creating account snapshot for {uid}")

    account_ref = db.collection("users").document(uid).collection("alpacaAccounts").document("demo_account")
    account_ref.set({
        "account_id": "demo_account",
        "environment": "paper",
        "equity": 100000.00,
        "buying_power": 50000.00,
        "cash": 25000.00,
        "portfolio_value": 100000.00,
        "day_pnl": 650.75,
        "day_pnl_pct": 0.0065,
        "margin_used": 50000.00,
        "margin_available": 150000.00,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "created_at": firestore.SERVER_TIMESTAMP,
    }, merge=True)

    print(f"[ACCOUNT] ✓ Created account snapshot")


def seed_sample_trades(db: firestore.Client, tenant_id: str, uid: str = "local") -> None:
    """Create sample trade records for demo."""
    print(f"[TRADES] Creating sample trades")

    now = datetime.utcnow()
    trades_ref = db.collection("tenants").document(tenant_id).collection("ledger_trades")

    trades = [
        {
            "uid": uid,
            "strategy_id": "demo",
            "run_id": "run_001",
            "symbol": "SPY",
            "side": "buy",
            "qty": 10,
            "price": 430.50,
            "ts": now - timedelta(hours=1),
            "fees": 10.00,
            "created_at": firestore.SERVER_TIMESTAMP,
        },
        {
            "uid": uid,
            "strategy_id": "demo",
            "run_id": "run_001",
            "symbol": "SPY",
            "side": "sell",
            "qty": 10,
            "price": 432.15,
            "ts": now - timedelta(minutes=30),
            "fees": 10.00,
            "created_at": firestore.SERVER_TIMESTAMP,
        },
        {
            "uid": uid,
            "strategy_id": "demo",
            "run_id": "run_002",
            "symbol": "QQQ",
            "side": "buy",
            "qty": 5,
            "price": 368.00,
            "ts": now - timedelta(minutes=15),
            "fees": 5.00,
            "created_at": firestore.SERVER_TIMESTAMP,
        },
    ]

    for i, trade in enumerate(trades):
        trade_id = f"trade_{now.strftime('%Y%m%d%H%M%S')}_{i}"
        trades_ref.document(trade_id).set(trade, merge=True)

    print(f"[TRADES] ✓ Created {len(trades)} sample trades")


def seed_live_quotes(db: firestore.Client, tenant_id: str) -> None:
    """Create sample live quotes for watchlist."""
    print(f"[QUOTES] Creating live quotes")

    quotes_ref = db.collection("tenants").document(tenant_id).collection("live_quotes")

    quotes = [
        {
            "symbol": "SPY",
            "bid_price": 430.40,
            "ask_price": 430.50,
            "last_trade_price": 430.45,
            "last_trade_size": 100,
            "bid_size": 1000,
            "ask_size": 1000,
            "timestamp": firestore.SERVER_TIMESTAMP,
        },
        {
            "symbol": "QQQ",
            "bid_price": 367.90,
            "ask_price": 368.00,
            "last_trade_price": 367.95,
            "last_trade_size": 100,
            "bid_size": 1000,
            "ask_size": 1000,
            "timestamp": firestore.SERVER_TIMESTAMP,
        },
        {
            "symbol": "AAPL",
            "bid_price": 177.90,
            "ask_price": 178.10,
            "last_trade_price": 178.00,
            "last_trade_size": 100,
            "bid_size": 1000,
            "ask_size": 1000,
            "timestamp": firestore.SERVER_TIMESTAMP,
        },
    ]

    for quote in quotes:
        symbol = quote["symbol"]
        quotes_ref.document(symbol).set(quote, merge=True)

    print(f"[QUOTES] ✓ Created {len(quotes)} live quotes")


def main():
    """Seed all demo data."""
    print("\n" + "="*60)
    print("AGENTTRADER V2 - DEMO DATA SEEDER")
    print("="*60 + "\n")

    # Initialize Firebase
    db, project_id = init_firebase()
    print(f"[INIT] Connected to project: {project_id}\n")

    try:
        # Seed data
        tenant_id = "demo_tenant"
        uid = "local"

        seed_tenant(db, tenant_id)
        seed_user(db, tenant_id, uid)
        seed_market_data(db, tenant_id)
        seed_account_data(db, uid)
        seed_sample_trades(db, tenant_id, uid)
        seed_live_quotes(db, tenant_id)

        print("\n" + "="*60)
        print("✓ DEMO DATA SEEDING COMPLETE")
        print("="*60)
        print(f"\nTenant ID: {tenant_id}")
        print(f"User ID: {uid}")
        print(f"Email: local@example.com")
        print(f"Project: {project_id}")
        print("\nYou can now:")
        print("  1. Sign in with local mode (or use demo@example.com if Firebase is configured)")
        print("  2. View watchlist (market_data_1m will populate sparklines)")
        print("  3. View account balance ($100,000)")
        print("  4. See sample trades in ledger")
        print("\n")

    except Exception as e:
        print(f"\n[ERROR] Failed to seed data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
