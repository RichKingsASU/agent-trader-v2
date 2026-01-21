import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scripts.lib.exec_guard as exec_guard

from backend.common.secrets import get_secret
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
    exec_guard.enforce_execution_policy(__file__, sys.argv)
    # Global kill-switch guard: never place even paper orders while halted.
    try:
        from backend.common.kill_switch import ExecutionHaltedError, require_live_mode  # type: ignore

        require_live_mode(operation="paper order placement")
    except ExecutionHaltedError as e:
        print(f"REFUSED: {e}")
        raise SystemExit(2)
    except Exception as e:
        print(f"REFUSED: could not evaluate kill switch: {e}")
        raise SystemExit(2)

    # dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env.local')
    # load_dotenv(dotenv_path=dotenv_path)

    api_key = get_secret("APCA_API_KEY_ID", fail_if_missing=True)
    secret_key = get_secret("APCA_API_SECRET_KEY", fail_if_missing=True)
    # Safety: if a base URL is configured, it must be paper-only.
    try:
        from backend.common.env import assert_paper_alpaca_base_url  # type: ignore

        base_url = get_secret("APCA_API_BASE_URL", fail_if_missing=False) or "https://paper-api.alpaca.markets"
        _ = assert_paper_alpaca_base_url(base_url)
    except Exception as e:
        print(f"REFUSED: invalid Alpaca trading base URL: {e}")
        raise SystemExit(2)

    api_key = (os.getenv("APCA_API_KEY_ID") or "").strip()
    secret_key = (os.getenv("APCA_API_SECRET_KEY") or "").strip()

    if not api_key or not secret_key:
        print("ERROR: APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env.local.")
        raise SystemExit(1)

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
            raise SystemExit(0)
        raise SystemExit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()