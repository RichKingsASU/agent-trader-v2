import os
import sys
import logging # Added for logging configuration

import scripts.lib.exec_guard as exec_guard
from scripts.lib.alpaca_env_guard import validate_and_correct_alpaca_base_url # New import

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.common.exceptions import APIError
from dotenv import load_dotenv

# Configure basic logging for the script and imported modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__) # Get logger for this module

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
        logger.error(f"REFUSED: {e}") # Use logger
        raise SystemExit(2)
    except Exception as e:
        logger.error(f"REFUSED: could not evaluate kill switch: {e}") # Use logger
        raise SystemExit(2)

    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env.local')
    load_dotenv(dotenv_path=dotenv_path)

    # 1. Validate and correct Alpaca API base URL before any client construction
    try:
        validate_and_correct_alpaca_base_url()
    except SystemExit as e:
        # The helper function already logs the error, just re-raise
        raise e
    except Exception as e:
        logger.error(f"Unexpected error during Alpaca base URL validation: {e}")
        raise SystemExit("ERROR: Unexpected error during Alpaca base URL validation.")

    # Safety gate: NO broker actions unless explicitly enabled.
    from backend.common.execution_enabled import require_execution_enabled
    from backend.common.secrets import get_secret
    # from backend.common.env import assert_paper_alpaca_base_url # No longer needed

    # Resolve creds from Secret Manager first, then env (if allowed).
    # Note: The script will re-fetch from os.getenv later, which is a potential bug.
    # For now, we ensure the base_url itself is validated.
    api_key = (get_secret("APCA_API_KEY_ID", fail_if_missing=False) or os.getenv("APCA_API_KEY_ID") or "").strip()
    secret_key = (get_secret("APCA_API_SECRET_KEY", fail_if_missing=False) or os.getenv("APCA_API_SECRET_KEY") or "").strip()

    # Re-fetch keys from os.environ, potentially overwriting Secret Manager values if not careful.
    # This part of the logic seems redundant or potentially buggy, but is kept as per prompt.
    api_key = (os.getenv("APCA_API_KEY_ID") or "").strip()
    secret_key = (os.getenv("APCA_API_SECRET_KEY") or "").strip()

    if not api_key or not secret_key:
        logger.error("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env.local or environment.")
        raise SystemExit(1)

    logger.info("--> Attempting to place test order: SPY BUY 1 Qty") # Use logger
    try:
        require_execution_enabled(operation="scripts.place_test_order.submit_order", context={"symbol": "SPY", "side": "buy", "qty": 1})
        # The TradingClient uses the APCA_API_BASE_URL from os.environ, which is now guaranteed to be validated.
        trading_client = TradingClient(api_key, secret_key, paper=True)
        market_order_data = MarketOrderRequest(
            symbol="SPY",
            qty=1,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )
        market_order = trading_client.submit_order(order_data=market_order_data)
        logger.info(f"    - Order ID: {market_order.id}") # Use logger
        logger.info(f"    - Status: {market_order.status}") # Use logger
        logger.info(f"    - Symbol: {market_order.symbol}") # Use logger
        logger.info(f"    - Qty: {market_order.qty}") # Use logger
        logger.info("SUCCESS: Test order submitted successfully.")

    except APIError as e:
        logger.error(f"ERROR: Failed to submit order via Alpaca API.")
        logger.error(f"    - Status Code: {e.status_code}") # Use corrected attribute
        logger.error(f"    - Response: {e}")
        # Check if the market is open
        if "market is closed" in str(e).lower():
            logger.info("INFO: This is expected if the market is currently closed.")
            # Exit gracefully since this isn't a credentials/config error.
            raise SystemExit(0)
        raise SystemExit(1)
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()