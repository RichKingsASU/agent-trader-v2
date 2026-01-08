# agenttrader/scripts/place_test_order.py
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError
from dotenv import load_dotenv
from backend.config.alpaca_env import load_alpaca_auth_env

def main():
    """
    Places a single 'SPY buy 1' market order using the Alpaca paper trading account.
    """
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env.local')
    load_dotenv(dotenv_path=dotenv_path)

    try:
        auth = load_alpaca_auth_env()
    except Exception:
        print("ERROR: Missing Alpaca credentials. Set APCA_API_KEY_ID, APCA_API_SECRET_KEY, and APCA_API_BASE_URL in .env.local.")
        exit(1)

    print("--> Placing test order: SPY BUY 1 Qty")
    try:
        trading_client = TradingClient(auth.api_key_id, auth.api_secret_key, paper=True)
        market_order_data = MarketOrderRequest(
            symbol="SPY",
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        market_order = trading_client.submit_order(order_data=market_order_data)
        print("    - Order ID:", market_order.id)
        print("    - Status:", market_order.status)
        print("    - Symbol:", market_order.symbol)
        print("    - Qty:", market_order.qty)
        print("SUCCESS: Test order submitted successfully.")

    except APIError as e:
        print(f"ERROR: Failed to submit order via Alpaca API.")
        print(f"    - Status Code: {e._status_code}")
        print(f"    - Response: {e}")
        # Check if the market is open
        if "market is closed" in str(e).lower():
            print("INFO: This is expected if the market is currently closed.")
            # Exit gracefully since this isn't a credentials/config error.
            exit(0)
        exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        exit(1)

if __name__ == "__main__":
    main()
