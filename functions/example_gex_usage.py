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
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import alpaca_trade_api as tradeapi
from functions.utils.gex_engine import calculate_net_gex, get_market_regime_summary


def main():
    """Main example function."""
    print("=" * 80)
    print("GEX (Gamma Exposure) Engine - Example Usage")
    print("=" * 80)
    print()
    
    # Initialize Alpaca API client
    key_id = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")
    base_url = os.getenv("APCA_API_BASE_URL")
    
    if not key_id or not secret_key:
        print("ERROR: Please set APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables")
        print()
        print("Example:")
        print("  export APCA_API_KEY_ID='your_key_id'")
        print("  export APCA_API_SECRET_KEY='your_secret_key'")
        print("  export APCA_API_BASE_URL='https://paper-api.alpaca.markets'")
        sys.exit(1)
    
    print(f"Connecting to Alpaca API: {base_url}")
    api = tradeapi.REST(
        key_id=key_id,
        secret_key=secret_key,
        base_url=base_url
    )
    print("✓ Connected successfully\n")
    
    # Calculate GEX for SPY and QQQ
    symbols = ["SPY", "QQQ"]
    
    for symbol in symbols:
        print("-" * 80)
        print(f"Calculating GEX for {symbol}...")
        print("-" * 80)
        
        try:
            # Calculate GEX
            gex_data = calculate_net_gex(symbol=symbol, api=api)
            
            # Display results
            print(f"\n📊 {symbol} GEX Results:")
            print(f"  Net GEX:          {gex_data['net_gex']}")
            print(f"  Volatility Bias:  {gex_data['volatility_bias']}")
            print(f"  Spot Price:       ${gex_data['spot_price']}")
            print(f"  Options Count:    {gex_data['option_count']}")
            print(f"  Call GEX:         {gex_data['total_call_gex']}")
            print(f"  Put GEX:          {gex_data['total_put_gex']}")
            print(f"  Timestamp:        {gex_data['timestamp']}")
            
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
            net_gex = Decimal(gex_data['net_gex'])
            
            if net_gex > Decimal("1000000"):
                print("  ✓ Strong positive GEX: Market makers will dampen volatility")
                print("    → Consider: Selling options premium (theta strategies)")
                print("    → Avoid: Chasing breakouts (likely to fade)")
            elif net_gex > Decimal("0"):
                print("  ✓ Positive GEX: Moderate price stabilization expected")
                print("    → Consider: Mean reversion strategies")
            elif net_gex > Decimal("-1000000"):
                print("  ⚠️  Negative GEX: Moderate volatility amplification")
                print("    → Consider: Trend following strategies")
                print("    → Increase: Hedging frequency (like GammaScalper does)")
            else:
                print("  🚨 Strong negative GEX: High volatility amplification risk!")
                print("    → Consider: Buying options (vega strategies)")
                print("    → Avoid: Selling premium (high gamma risk)")
                print("    → Increase: Position monitoring and risk controls")
            
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
    main()
