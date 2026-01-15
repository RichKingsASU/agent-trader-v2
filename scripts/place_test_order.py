from backend.common.secrets import get_secret
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError

def main():
    """
    Places a single 'SPY buy 1' market order using the Alpaca paper trading account.
    """
    # Global kill-switch guard: never place even paper orders while halted.
    try:
        from backend.common.kill_switch import get_kill_switch_state  # type: ignore

        enabled, source = get_kill_switch_state()
        if enabled:
            print(f"REFUSED: kill switch is active (source={source}). Set EXECUTION_HALTED=0 to proceed.")
            exit(2)
    except Exception:
        # Best-effort safety: if we cannot evaluate the kill-switch module, do not block the script.
        # (The runtime execution engine has its own defenses.)
        pass

    try:
        from backend.common.alpaca_env import configure_alpaca_env  # type: ignore

        alpaca = configure_alpaca_env(required=True)
    except Exception as e:
        print(f"ERROR: unable to configure Alpaca credentials from Secret Manager: {e}")
        exit(1)

    api_key = alpaca.api_key_id
    secret_key = alpaca.api_secret_key

    print("--> Placing test order: SPY BUY 1 Qty")
    try:
        trading_client = TradingClient(api_key, secret_key, paper=True)
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