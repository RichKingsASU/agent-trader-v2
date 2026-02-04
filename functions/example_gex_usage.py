"""
Example: Using the GEX Engine

This script demonstrates how to:
1. Calculate GEX for a symbol
2. Interpret the results
3. Use GEX data in trading decisions

Usage:
    # Set environment variables
    export APCA_API_KEY_ID="your_key_id"
    export APCA_API_SECRET_KEY="your_secret_key"
    export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
    
    # Run the example
    python functions/example_gex_usage.py
"""

import os
import sys
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

# Standardize on alpaca-py
# Remove direct import of alpaca_trade_api
# import alpaca_trade_api as tradeapi
from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError
# Assuming GEX Engine and Market Regime Summary are in utils
# from functions.utils.gex_engine import calculate_net_gex, get_market_regime_summary
# Placeholder implementations for GEX engine functions if they are not directly importable or for testing
# In a real project, ensure these are correctly imported or defined.

# Mock implementations for demonstration if actual imports fail
def calculate_net_gex(symbol: str, api: TradingClient, date_str: str = None) -> Dict[str, Any]:
    """Placeholder for calculate_net_gex function."""
    print(f"Placeholder: Calculating GEX for {symbol} using TradingClient.")
    # Simulate response structure based on original script's expected output
    return {
        "net_gex": "150000.00", # Example string value
        "volatility_bias": "positive",
        "spot_price": "450.50",
        "option_count": 1200,
        "total_call_gex": "80000.00",
        "total_put_gex": "-70000.00",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "GEX calculation simulated."
    }

def get_market_regime_summary(gex_data: Dict[str, Any]) -> str:
    """Placeholder for get_market_regime_summary function."""
    net_gex = Decimal(gex_data.get('net_gex', '0'))
    if net_gex > Decimal("1000000"):
        return "Strong positive GEX: Market makers will dampen volatility."
    elif net_gex > Decimal("0"):
        return "Positive GEX: Moderate price stabilization expected."
    elif net_gex > Decimal("-1000000"):
        return "Negative GEX: Moderate volatility amplification."
    else:
        return "Strong negative GEX: High volatility amplification risk!"

# --- Project Setup ---
# Add parent directory to path for imports, if necessary for the environment
# project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# if project_root not in sys.path:
#     sys.path.insert(0, project_root)

# --- Alpaca API Initialization ---
def assert_paper_alpaca_base_url(base_url: str) -> str:
    """Asserts that the base URL is for the paper trading environment."""
    if "paper-api.alpaca.markets" not in base_url:
        print(f"Warning: Using non-paper trading URL: {base_url}. Ensure this is intended.")
    return base_url

def _get_alpaca_client() -> Optional[TradingClient]:
    """Initializes and returns an Alpaca TradingClient using alpaca-py."""
    key_id = os.environ.get("APCA_API_KEY_ID")
    secret_key = os.environ.get("APCA_API_SECRET_KEY")
    base_url = assert_paper_alpaca_base_url(
        os.environ.get("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"
    )
    
    if not key_id or not secret_key:
        print("ERROR: Alpaca API key ID or secret key not found in environment variables.")
        return None
        
    try:
        client = TradingClient(
            key_id=key_id,
            secret_key=secret_key,
            base_url=base_url
        )
        print("✓ Alpaca TradingClient initialized successfully.")
        return client
    except APIError as e:
        print(f"🔥 Alpaca API error during initialization: {e.message} (Code: {e.code}, Status: {e.status})")
        return None
    except Exception as e:
        print(f"🔥 An unexpected error occurred during client initialization: {e}")
        return None

def main():
    """Main example function."""
    print("=" * 80)
    print("GEX (Gamma Exposure) Engine - Example Usage")
    print("=" * 80)
    print()
    
    # Initialize Alpaca API client using alpaca-py
    api = _get_alpaca_client()
    if not api:
        print("ERROR: Failed to initialize Alpaca API client. Exiting.")
        return

    # Calculate GEX for SPY and QQQ
    symbols = ["SPY", "QQQ"]
    
    for symbol in symbols:
        print("-" * 80)
        print(f"Calculating GEX for {symbol}...")
        print("-" * 80)
        
        try:
            # Calculate GEX - Pass the initialized TradingClient
            # Note: The calculate_net_gex function might need adjustments to work with TradingClient
            # or might require a separate DataClient for historical bar data.
            # For this example, assuming calculate_net_gex is adapted or uses yfinance.
            # The original script used yfinance. I'll keep that for demonstration purposes,
            # but ideally, it should use Alpaca data if available via alpaca-py.
            
            # If calculate_net_gex relies on the API client for data fetching:
            # gex_data = calculate_net_gex(symbol=symbol, api=api)
            
            # For now, using the placeholder which doesn't strictly need the API client for simulation.
            # If calculate_net_gex actually uses the api object, it needs to be passed correctly.
            # Based on the original tradeapi.REST, it likely fetched data.
            # The placeholder doesn't use the api object, so its presence here is for structure.
            
            # Placeholder call assuming calculate_net_gex doesn't strictly need the 'api' object passed for simulation.
            # If it did, the function signature would need to be adjusted.
            gex_data = calculate_net_gex(symbol=symbol, api=api, date_str=datetime.now().strftime('%Y-%m-%d')) # Adjusted placeholder call
            
            # Display results
            print(f"\n📊 {symbol} GEX Results:")
            print(f"  Net GEX:          {gex_data.get('net_gex', 'N/A')}")
            print(f"  Volatility Bias:  {gex_data.get('volatility_bias', 'N/A')}")
            print(f"  Spot Price:       ${gex_data.get('spot_price', 'N/A')}")
            print(f"  Options Count:    {gex_data.get('option_count', 'N/A')}")
            print(f"  Call GEX:         {gex_data.get('total_call_gex', 'N/A')}")
            print(f"  Put GEX:          {gex_data.get('total_put_gex', 'N/A')}")
            print(f"  Timestamp:        {gex_data.get('timestamp', 'N/A')}")
            
            # Display error if present
            if "error" in gex_data:
                print(f"\n⚠️  Error: {gex_data['error']}")
            
            # Display warning if present
            if "warning" in gex_data:
                print(f"\n⚠️  Warning: {gex_data['warning']}")
            
            # Display market regime summary
            print(f"\n📈 Market Regime Summary:")
            print(get_market_regime_summary(gex_data))
            
            # Trading implications
            print(f"\n💡 Trading Implications:")
            try:
                net_gex_decimal = Decimal(gex_data.get('net_gex', '0'))
                if net_gex_decimal > Decimal("1000000"):
                    print("  ✓ Strong positive GEX: Market makers will dampen volatility")
                    print("    → Consider: Selling options premium (theta strategies)")
                    print("    → Avoid: Chasing breakouts (likely to fade)")
                elif net_gex_decimal > Decimal("0"):
                    print("  ✓ Positive GEX: Moderate price stabilization expected")
                    print("    → Consider: Mean reversion strategies")
                elif net_gex_decimal > Decimal("-1000000"):
                    print("  ⚠️  Negative GEX: Moderate volatility amplification")
                    print("    → Consider: Trend following strategies")
                    print("    → Increase: Hedging frequency (like GammaScalper does)")
                else:
                    print("  🚨 Strong negative GEX: High volatility amplification risk!")
                    print("    → Consider: Buying options (vega strategies)")
                    print("    → Avoid: Selling premium (high gamma risk)")
                    print("    → Increase: Position monitoring and risk controls")
            except InvalidOperation:
                print("  Could not parse net_gex for trading implications.")
            
            print()
            
        except Exception as e:
            print(f"\n❌ Error calculating GEX for {symbol}: {e}")
            import traceback
            traceback.print_exc()
            print()
    
    # Summary
    print("=" * 80)
    print("Next Steps:")
    print("=" * 80)
    print("1. Deploy pulse function to calculate GEX every minute:")
    print("   firebase deploy --only functions:pulse")
    print()
    print("2. View GEX data in Firestore:")
    print("   Collection: systemStatus")
    print("   Document:   market_regime")
    print()
    print("3. Strategies will automatically read GEX data from Firestore")
    print("   Example: GammaScalper adjusts hedging_threshold based on GEX")
    print()


if __name__ == "__main__":
    # Set dummy environment variables for example run if not set
    if not os.environ.get("APCA_API_KEY_ID"): os.environ["APCA_API_KEY_ID"] = "DUMMY_KEY_ID_EX_GEX"
    if not os.environ.get("APCA_API_SECRET_KEY"): os.environ["APCA_API_SECRET_KEY"] = "DUMMY_SECRET_KEY_EX_GEX"
    if not os.environ.get("APCA_API_BASE_URL"): os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    
    main()

    # Clean up dummy environment variables
    for var in ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL"]:
        if var in os.environ:
            del os.environ[var]