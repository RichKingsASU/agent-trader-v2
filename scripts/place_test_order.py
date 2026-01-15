import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError
# from dotenv import load_dotenv

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

    # dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env.local')
    # load_dotenv(dotenv_path=dotenv_path)

    # Safety gate: NO broker actions unless explicitly enabled.
    from backend.common.execution_enabled import require_execution_enabled
    from backend.common.secrets import get_secret
    from backend.common.env import assert_paper_alpaca_base_url

    # Resolve creds from Secret Manager first, then env (if allowed).
    api_key = (get_secret("APCA_API_KEY_ID", fail_if_missing=False) or os.getenv("APCA_API_KEY_ID") or "").strip()
    secret_key = (get_secret("APCA_API_SECRET_KEY", fail_if_missing=False) or os.getenv("APCA_API_SECRET_KEY") or "").strip()

    # Safety: if a base URL is configured, it must be paper-only (and HTTPS).
    base_url = (get_secret("APCA_API_BASE_URL", fail_if_missing=False) or os.getenv("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets").strip()
    try:
        _ = assert_paper_alpaca_base_url(base_url)
    except Exception as e:
        print(f"REFUSED: invalid Alpaca trading base URL: {e}")
        exit(2)

    if not api_key or not secret_key:
        print("ERROR: APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env.local.")
        exit(1)

    print("--> Placing test order: SPY BUY 1 Qty")
    try:
        require_execution_enabled(operation="scripts.place_test_order.submit_order", context={"symbol": "SPY", "side": "buy", "qty": 1})
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