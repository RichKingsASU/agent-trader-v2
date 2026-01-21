import argparse
import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError

# Import get_secret for DATABASE_URL retrieval
from backend.common.secrets import get_secret

def main():
    """
    Inserts a single paper trading order into the database.
    """
    parser = argparse.ArgumentParser(description="Insert a single Alpaca PAPER test order (safety-gated).")
    parser.add_argument(
        "--execution-confirm",
        required=True,
        help="Required safety confirmation token (must match EXECUTION_CONFIRM_TOKEN).",
    )
    args = parser.parse_args()

    # Global kill-switch guard: never place even paper orders while halted (fail-closed).
    try:
        from backend.common.kill_switch import ExecutionHaltedError, require_live_mode  # type: ignore

        require_live_mode(operation="paper order placement")
    except ExecutionHaltedError as e:
        print(f"REFUSED: {e}")
        raise SystemExit(2)
    except Exception as e:
        print(f"REFUSED: could not evaluate kill switch: {e}")
        raise SystemExit(2)

    # Retrieve DATABASE_URL using get_secret for mandatory access.
    url = get_secret("DATABASE_URL", fail_if_missing=True)

    if not url:
        print("ERROR: DATABASE_URL is missing and essential for operation.")
        exit(1)

    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")
    from backend.common.env import assert_paper_alpaca_base_url, is_execution_enabled  # type: ignore

    if not is_execution_enabled():
        print("REFUSED: execution is disabled (set EXECUTION_ENABLED=1 to allow paper order placement).")
        raise SystemExit(2)

    expected = (os.getenv("EXECUTION_CONFIRM_TOKEN") or "").strip()
    if not expected:
        print("REFUSED: missing EXECUTION_CONFIRM_TOKEN (required for any order placement).")
        raise SystemExit(2)
    if str(args.execution_confirm).strip() != expected:
        print("REFUSED: EXECUTION_CONFIRM mismatch (token did not match EXECUTION_CONFIRM_TOKEN).")
        raise SystemExit(2)

    # Safety: if a base URL is configured, it must be paper-only.
    try:
        _ = assert_paper_alpaca_base_url(os.getenv("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets")
    except Exception as e:
        print(f"REFUSED: invalid Alpaca trading base URL: {e}")
        raise SystemExit(2)

    if not api_key or not secret_key:
        print("ERROR: APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env.local.")
        exit(1)

    print("--> Inserting test order into DB: SPY BUY 1 Qty")
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

if __name__ == "__main__":
    main()