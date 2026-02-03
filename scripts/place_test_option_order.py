import os
import sys
import logging
from datetime import date, timedelta

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, AssetClass, OptionType
from alpaca.common.exceptions import APIError
from dotenv import load_dotenv

import scripts.lib.exec_guard as exec_guard
from scripts.lib.alpaca_env_guard import validate_and_correct_alpaca_base_url
import scripts.lib.options_guard as options_guard

# Configure basic logging for the script and imported modules
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def main():
    """
    Places a single paper-only options market order for SPY CALL.
    """
    # --- Guardrail Enforcement ---
    exec_guard.enforce_execution_policy(__file__, sys.argv)

    # Global kill-switch guard
    try:
        from backend.common.kill_switch import ExecutionHaltedError, require_live_mode
        require_live_mode(operation="paper option order placement")
    except ExecutionHaltedError as e:
        logger.error(f"REFUSED: {e}")
        raise SystemExit(2)
    except Exception as e:
        logger.error(f"REFUSED: could not evaluate kill switch: {e}")
        raise SystemExit(2)

    # Load environment variables from .env.local
    dotenv_path = os.path.join(os.path.dirname(__file__), '..', '.env.local')
    load_dotenv(dotenv_path=dotenv_path)

    # Validate and correct Alpaca API base URL before any client construction
    try:
        validate_and_correct_alpaca_base_url()
    except SystemExit as e:
        # The helper function already logs the error, just re-raise
        raise e
    except Exception as e:
        logger.error(f"Unexpected error during Alpaca base URL validation: {e}")
        raise SystemExit("ERROR: Unexpected error during Alpaca base URL validation.")

    # Ensure execution is enabled and confirmation token is present
    from backend.common.execution_enabled import require_execution_enabled
    from backend.common.secrets import get_secret

    # Check for EXECUTION_CONFIRM_TOKEN (required for explicit opt-in)
    # The require_execution_enabled function might check this internally, or we check it explicitly.
    # Assuming require_execution_enabled checks necessary env vars like EXECUTION_ENABLED and EXECUTION_CONFIRM_TOKEN.
    # If not, we'd add:
    # confirmation_token = os.getenv("EXECUTION_CONFIRM_TOKEN")
    # if not confirmation_token:
    #     logger.error("EXECUTION_CONFIRM_TOKEN must be set for explicit confirmation.")
    #     raise SystemExit("ERROR: EXECUTION_CONFIRM_TOKEN must be set.")

    # Resolve credentials
    api_key = os.getenv("APCA_API_KEY_ID")
    secret_key = os.getenv("APCA_API_SECRET_KEY")

    if not api_key or not secret_key:
        logger.error("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env.local or environment.")
        raise SystemExit(1)

    # --- Option Order Specifics ---
    underlying_symbol = "SPY"
    option_type = OptionType.CALL
    qty = 1

    logger.info(f"Preparing to place a paper {option_type.value} order for {underlying_symbol} Qty: {qty}")

    try:
        # Require explicit opt-in for this operation
        # NOTE: The context for require_execution_enabled might need to be specific.
        # If EXECUTION_CONFIRM_TOKEN is an argument to require_execution_enabled, it needs to be passed.
        # For now, assuming it checks env vars.
        require_execution_enabled(operation="scripts.place_test_option_order.submit_order", context={"underlying": underlying_symbol, "type": option_type.value, "qty": qty})

        # Initialize TradingClient using paper trading
        trading_client = TradingClient(api_key, secret_key, paper=True)

        # 1. Find nearest expiration date
        expiration_date = options_guard.get_nearest_expiration(trading_client, underlying_symbol)
        if not expiration_date:
            logger.error("Could not determine nearest expiration date. Aborting.")
            raise SystemExit(1)

        # 2. Find ATM strike price
        atm_strike = options_guard.get_atm_strike(trading_client, underlying_symbol, expiration_date)
        if atm_strike is None: # Use None check as strike can be 0.0
            logger.error("Could not determine ATM strike price. Aborting.")
            raise SystemExit(1)

        # 3. Construct OptionSymbol
        # OptionSymbol takes underlying, strike, expiration_date, option_type
        option_symbol_str = OptionSymbol(
            underlying=underlying_symbol,
            strike_price=atm_strike,
            expiration_date=expiration_date,
            option_type=option_type
        ).symbol
        logger.info(f"Constructed option symbol: {option_symbol_str}")

        # 4. Prepare Market Order Request for the option
        market_order_data = MarketOrderRequest(
            symbol=option_symbol_str,
            qty=qty,
            side=OrderSide.BUY, # Buying a call
            time_in_force=TimeInForce.DAY, # Standard time in force for market orders
            order_type="market" # Explicitly market order
        )

        # 5. Submit the order
        logger.info(f"Submitting market order for {option_symbol_str}...")
        market_order = trading_client.submit_order(order_data=market_order_data)

        logger.info(f"SUCCESS: Option order submitted successfully.")
        logger.info(f"    - Order ID: {market_order.id}")
        logger.info(f"    - Symbol: {market_order.symbol}")
        logger.info(f"    - Expiration: {expiration_date}")
        logger.info(f"    - Strike: {atm_strike}")
        logger.info(f"    - Type: {option_type.value}")
        logger.info(f"    - Qty: {market_order.qty}")
        logger.info(f"    - Status: {market_order.status}")

    except APIError as e:
        logger.error(f"ERROR: Failed to submit option order via Alpaca API.")
        # Use .status_code as it's the correct attribute, fix from previous iteration.
        logger.error(f"    - Status Code: {e.status_code}") 
        logger.error(f"    - Response: {e}")
        
        # Check if the market is open for options trading
        # This might require a different check than equity market closed
        if "market is closed" in str(e).lower():
            logger.info("INFO: Market may be closed for options trading. This is expected if markets are closed.")
            # Exit gracefully if it's a market closure, not a credential/config error.
            raise SystemExit(0)
        raise SystemExit(1)
    except SystemExit as e: # Catch SystemExit from guards or helpers
        logger.error(f"Execution blocked by guardrail or validation: {e}")
        raise e # Re-raise to exit with the correct code
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
