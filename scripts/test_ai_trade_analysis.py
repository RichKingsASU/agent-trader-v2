#!/usr/bin/env python3
"""
Test script for AI-powered trade analysis feature.

This script demonstrates the complete flow:
1. Create a shadow trade (OPEN)
2. Close the trade (triggers AI analysis)
3. Wait for Gemini analysis
4. Display results

Usage:
    python scripts/test_ai_trade_analysis.py
"""

import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import firestore
from backend.persistence.firebase_client import require_firestore_emulator_or_allow_prod


def create_test_shadow_trade(db: firestore.Client, user_id: str = "test_user_123") -> str:
    """
    Create a test shadow trade in Firestore.
    
    Returns:
        shadow_id: Document ID of created trade
    """
    shadow_id = str(uuid4())
    
    shadow_trade = {
        "shadow_id": shadow_id,
        "uid": user_id,
        "tenant_id": "test_tenant",
        "broker_account_id": "test_broker_123",
        "strategy_id": "gamma_scalper_v1",
        "symbol": "SPY",
        "instrument_type": "equity",
        "side": "BUY",
        "order_type": "market",
        "time_in_force": "day",
        "notional": "4500.00",
        "quantity": "10",
        "entry_price": "450.50",
        "status": "OPEN",
        "created_at": firestore.SERVER_TIMESTAMP,
        "created_at_iso": datetime.now(timezone.utc).isoformat(),
        # Market context for AI analysis
        "metadata": {
            "net_gex": "1500000000",  # +$1.5B (Bullish GEX)
            "volatility_bias": "Bullish",
            "sentiment": "Positive",
            "gex_regime": "LONG_GAMMA",
        },
        "reasoning": "Positive GEX regime detected. Market makers are long gamma, providing support on dips. Buying SPY at VWAP support with volume confirmation.",
        # P&L tracking fields
        "current_pnl": "0.00",
        "pnl_percent": "0.00",
        "current_price": "450.50",
        "last_updated": firestore.SERVER_TIMESTAMP,
    }
    
    # Create document
    db.collection("shadowTradeHistory").document(shadow_id).set(shadow_trade)
    
    print(f"✅ Created shadow trade: {shadow_id}")
    print(f"   Symbol: SPY")
    print(f"   Entry: $450.50")
    print(f"   Status: OPEN")
    print(f"   GEX: +$1.5B (Bullish)")
    
    return shadow_id


def close_test_shadow_trade(db: firestore.Client, shadow_id: str) -> None:
    """
    Close a test shadow trade and trigger AI analysis.
    """
    shadow_ref = db.collection("shadowTradeHistory").document(shadow_id)
    shadow_doc = shadow_ref.get()
    
    if not shadow_doc.exists:
        print(f"❌ Shadow trade {shadow_id} not found")
        return
    
    shadow_data = shadow_doc.to_dict()
    
    # Simulate profitable exit
    exit_price = Decimal("452.00")
    entry_price = Decimal(shadow_data["entry_price"])
    quantity = Decimal(shadow_data["quantity"])
    
    # Calculate P&L
    pnl = (exit_price - entry_price) * quantity
    pnl_percent = (pnl / (entry_price * quantity)) * Decimal("100")
    
    # Update to CLOSED status (this triggers the Cloud Function)
    update_data = {
        "status": "CLOSED",
        "exit_price": str(exit_price),
        "exit_reason": "Profit target hit at resistance",
        "closed_at": firestore.SERVER_TIMESTAMP,
        "closed_at_iso": datetime.now(timezone.utc).isoformat(),
        "final_pnl": str(pnl),
        "final_pnl_percent": str(pnl_percent),
        "current_pnl": str(pnl),
        "pnl_percent": str(pnl_percent),
    }
    
    shadow_ref.update(update_data)
    
    print(f"\n✅ Closed shadow trade: {shadow_id}")
    print(f"   Exit: ${exit_price}")
    print(f"   P&L: ${pnl} ({pnl_percent:.2f}%)")
    print(f"   Status: CLOSED → Triggering AI analysis...")


def wait_for_ai_analysis(db: firestore.Client, shadow_id: str, timeout: int = 30) -> dict:
    """
    Wait for AI analysis to complete and return results.
    
    Args:
        db: Firestore client
        shadow_id: Trade ID
        timeout: Max seconds to wait
        
    Returns:
        AI analysis dict or None if timeout
    """
    print(f"\n⏳ Waiting for Gemini 1.5 Flash analysis (max {timeout}s)...")
    
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        shadow_ref = db.collection("shadowTradeHistory").document(shadow_id)
        shadow_doc = shadow_ref.get()
        
        if shadow_doc.exists:
            shadow_data = shadow_doc.to_dict()
            ai_analysis = shadow_data.get("ai_analysis")
            
            if ai_analysis:
                elapsed = time.time() - start_time
                print(f"✅ AI analysis complete in {elapsed:.1f}s")
                return ai_analysis
        
        time.sleep(2)  # Check every 2 seconds
    
    print(f"⏱️ Timeout after {timeout}s - AI analysis not complete")
    return None


def display_ai_analysis(analysis: dict) -> None:
    """
    Pretty-print AI analysis results.
    """
    print("\n" + "=" * 60)
    print("🤖 AI POST-GAME ANALYSIS")
    print("=" * 60)
    print(f"\n📊 GRADE: {analysis.get('grade', 'N/A')}")
    print(f"\n💡 QUANT TIP:")
    print(f"   {analysis.get('feedback', 'No feedback provided')}")
    print(f"\n🕒 Analyzed: {analysis.get('analyzed_at', 'Unknown')}")
    print(f"🤖 Model: {analysis.get('model', 'Unknown')}")
    print("=" * 60 + "\n")


def main():
    """
    Main test flow.
    """
    print("🚀 AI Trade Analysis Test Script")
    print("=" * 60 + "\n")
    
    # Initialize Firestore
    try:
        require_firestore_emulator_or_allow_prod(caller="scripts.test_ai_trade_analysis.main")
        db = firestore.Client()
        print("✅ Connected to Firestore\n")
    except Exception as e:
        print(f"❌ Failed to connect to Firestore: {e}")
        print("\nMake sure you have:")
        print("  1. GOOGLE_APPLICATION_CREDENTIALS environment variable set")
        print("  2. Firebase Admin SDK initialized")
        print("  3. Firestore database created")
        return
    
    # Step 1: Create test shadow trade
    try:
        shadow_id = create_test_shadow_trade(db)
    except Exception as e:
        print(f"❌ Failed to create shadow trade: {e}")
        return
    
    # Wait a moment
    time.sleep(2)
    
    # Step 2: Close the trade (triggers AI analysis)
    try:
        close_test_shadow_trade(db, shadow_id)
    except Exception as e:
        print(f"❌ Failed to close shadow trade: {e}")
        return
    
    # Step 3: Wait for AI analysis
    try:
        ai_analysis = wait_for_ai_analysis(db, shadow_id, timeout=30)
    except Exception as e:
        print(f"❌ Error waiting for AI analysis: {e}")
        return
    
    # Step 4: Display results
    if ai_analysis:
        display_ai_analysis(ai_analysis)
        print("✅ Test completed successfully!")
    else:
        print("\n❌ AI analysis did not complete in time.")
        print("\nTroubleshooting:")
        print("  1. Check Cloud Function is deployed: firebase deploy --only functions:analyze_closed_trade")
        print("  2. Verify Vertex AI credentials are configured")
        print("  3. Check Cloud Function logs: firebase functions:log")
        print(f"  4. Manually check Firestore document: shadowTradeHistory/{shadow_id}")
    
    print(f"\n📄 Trade ID: {shadow_id}")
    print("   You can view this in Firebase Console:")
    print(f"   Firestore → shadowTradeHistory → {shadow_id}")


if __name__ == "__main__":
    main()
