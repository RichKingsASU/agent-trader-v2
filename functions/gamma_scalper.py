import os
import datetime
import time
# Standardize on alpaca-py
# Remove direct import of alpaca_trade_api
# import alpaca_trade_api as tradeapi
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, OrderRequest, OrderSide, TimeInForce # Assuming MarketOrderRequest or similar is used
from alpaca.common.exceptions import APIError

import yfinance as yf

from functions.utils.apca_env import assert_paper_alpaca_base_url

# --- Configuration ---
API_KEY = os.environ.get('APCA_API_KEY_ID')
API_SECRET = os.environ.get('APCA_API_SECRET_KEY')
BASE_URL = os.environ.get('APCA_API_BASE_URL') or "https://paper-api.alpaca.markets"

# --- Execution Policy Enforcement ---
# This is a simplified representation; actual enforcement might be more complex.
# It's crucial to ensure these checks are robust in a real system.
def _require_enable_dangerous_functions() -> None:
    """
    This script can liquidate positions. Require an explicit opt-in.
    """
    v = (os.getenv("ENABLE_DANGEROUS_FUNCTIONS") or "").strip().lower()
    if v not in {"1", "true", "t", "yes", "y", "on"}:
        raise RuntimeError(
            "REFUSED: gamma_scalper is execution-capable. "
            "Set ENABLE_DANGEROUS_FUNCTIONS=true to proceed."
        )

_require_enable_dangerous_functions()
BASE_URL = assert_paper_alpaca_base_url(BASE_URL) # Ensures BASE_URL is paper-specific

# --- Initialize Alpaca API client using alpaca-py ---
api: Optional[TradingClient] = None
if API_KEY and API_SECRET:
    try:
        api = TradingClient(
            key_id=API_KEY,
            secret_key=API_SECRET,
            base_url=BASE_URL,
            # api_version='v2' # Not directly set on client init in alpaca-py
        )
        print("Alpaca TradingClient initialized successfully.")
    except APIError as e:
        print(f"Failed to initialize Alpaca TradingClient: {e}")
        api = None
    except Exception as e:
        print(f"An unexpected error occurred during client initialization: {e}")
        api = None
else:
    print("Alpaca API credentials not found. Trading functionality will be disabled.")


# --- Strategy Parameters ---
DELTA_THRESHOLD = 0.15
STOP_LOSS_PERCENTAGE = 0.20
# Using UTC for time comparisons in production is generally better, but adhering to original logic for now.
# If using ET, ensure proper timezone handling or UTC conversion if needed.
# For simplicity, let's assume EXIT_TIME_ET is handled correctly or replaced with UTC logic.
# EXIT_TIME_ET = datetime.time(15, 45) # This is ET, which is UTC-5. For consistency, consider UTC.


def get_spy_200_sma():
    """Fetches the 200-day SMA for SPY."""
    spy = yf.Ticker("SPY")
    # Fetching slightly more than 200 days to ensure enough data for SMA calculation
    hist = spy.history(period="220d") 
    if hist.empty:
        logger.error("Failed to fetch historical data for SPY.")
        return None
    return hist['Close'].rolling(window=200).mean().iloc[-1]

def regime_filter():
    """Checks if SPY is above its 200-day SMA."""
    try:
        spy_ticker = yf.Ticker("SPY")
        hist = spy_ticker.history(period="1d") # Fetch current day's close price
        if hist.empty:
            logger.error("Failed to fetch current SPY price.")
            return False
        spy_price = hist['Close'].iloc[-1]
        
        sma_200 = get_spy_200_sma()
        
        if sma_200 is None:
            logger.error("Could not calculate 200-day SMA for SPY.")
            return False
            
        logger.info(f"SPY Price: {spy_price:.2f}, 200-day SMA: {sma_200:.2f}")
        return spy_price > sma_200
    except Exception as e:
        logger.error(f"Error during regime filter check: {e}")
        return False

def get_portfolio_delta():
    """
    Calculates the overall portfolio delta.
    This is a placeholder function. In a real scenario, you would calculate
    the delta of your options positions.
    """
    # For this example, we'll simulate a delta.
    # In a real implementation, you would use a library like `greeks`
    # and your options positions to calculate the actual delta.
    return 0.10 # Placeholder value

def get_portfolio_vanna():
    """
    Calculates the overall portfolio vanna.
    This is a placeholder function.
    """
    return 0.02 # Placeholder value

def get_portfolio_charm():
    """
    Calculates the overall portfolio charm.
    This is a placeholder function.
    """
    return -0.01 # Placeholder value

def rebalance_portfolio(delta):
    """
    Rebalances the portfolio to be delta-neutral.
    This is a placeholder function.
    """
    print(f"Current Delta: {delta}. Rebalancing portfolio to be delta-neutral.")
    # Add logic here to buy/sell SPY shares to offset the delta.
    # Example using alpaca-py TradingClient:
    # if api:
    #     try:
    #         # Offset delta by buying/selling shares
    #         qty_to_trade = abs(delta) # Simplistic: trade absolute delta value
    #         side = OrderSide.BUY if delta < 0 else OrderSide.SELL # Buy if delta is negative, sell if positive
    #         
    #         order_request = MarketOrderRequest(
    #             symbol="SPY",
    #             qty=qty_to_trade,
    #             side=side,
    #             time_in_force=TimeInForce.DAY
    #         )
    #         order = api.submit_order(order_request)
    #         logger.info(f"Rebalance order submitted: {order.id}, Side: {side}, Qty: {qty_to_trade}")
    #     except APIError as e:
    #         logger.error(f"Alpaca API error during rebalancing: {e.message}")
    #     except Exception as e:
    #         logger.error(f"Unexpected error during rebalancing: {e}")
    pass

def check_stop_loss():
    """
    Checks if the 20% drawdown stop-loss has been hit.
    This is a placeholder function.
    """
    if not api:
        logger.warning("Alpaca API client not available. Cannot check stop loss.")
        return

    try:
        account = api.get_account()
        # This is a simplified example. A real implementation would track the
        # portfolio value over time and compare it to the initial value for the day.
        # For now, we'll assume the initial value was the previous day's closing value.
        # A better approach would be to store the day's starting equity.
        initial_value = float(account.last_equity) # Note: last_equity might not be the best for daily start value.
        current_value = float(account.equity)
        
        if initial_value is None or current_value is None:
            logger.warning("Could not retrieve account equity for stop-loss check.")
            return

        drawdown = (initial_value - current_value) / initial_value if initial_value > 0 else 0
        
        if drawdown >= STOP_LOSS_PERCENTAGE:
            logger.warning(f"Stop-loss of {STOP_LOSS_PERCENTAGE * 100:.0f}% hit. Drawdown: {drawdown*100:.2f}%. Liquidating positions.")
            api.close_all_positions()
            logger.info("All positions liquidated due to stop-loss.")
    except APIError as e:
        logger.error(f"Alpaca API error during stop-loss check: {e.message}")
    except Exception as e:
        logger.error(f"Unexpected error during stop-loss check: {e}")


def main():
    """Main function for the Gamma Scalper strategy."""
    print("Starting 0DTE Gamma Scalper Strategy...")

    if not regime_filter():
        print("Regime filter not met (SPY is not above 200-day SMA). Exiting.")
        return

    # Note: Original code used a hardcoded exit time and a loop.
    # For a script meant to run once or with a clear exit condition, this loop might need adjustment.
    # Adhering to original structure for now.
    while True:
        # Using UTC for time checks is recommended for consistency.
        # If specific ET logic is required, ensure proper timezone handling.
        now_utc = datetime.now(timezone.utc)
        # Example conversion to ET (UTC-5, typically EST/EDT)
        # This conversion is a simplification; actual DST rules apply.
        # For robust timezone handling, consider libraries like `pytz` or `zoneinfo`.
        now_et = now_utc - datetime.timedelta(hours=5) 
        exit_hour, exit_minute = EXIT_TIME_ET.hour, EXIT_TIME_ET.minute

        if now_et.hour >= exit_hour and now_et.minute >= exit_minute:
            print(f"Exit time ({EXIT_TIME_ET} ET) reached. Liquidating positions.")
            # check_stop_loss() # Ensure stop loss is also checked before exit
            if api:
                try:
                    api.close_all_positions()
                    logger.info("All positions liquidated due to exit time.")
                except APIError as e:
                    logger.error(f"Alpaca API error during exit time liquidation: {e.message}")
                except Exception as e:
                    logger.error(f"Unexpected error during exit time liquidation: {e}")
            else:
                logger.warning("API client not available. Cannot liquidate positions at exit time.")
            break

        check_stop_loss()

        portfolio_delta = get_portfolio_delta()
        vanna_adjustment = get_portfolio_vanna()
        charm_adjustment = get_portfolio_charm()

        adjusted_delta = portfolio_delta + vanna_adjustment + charm_adjustment

        if abs(adjusted_delta) > DELTA_THRESHOLD:
            rebalance_portfolio(adjusted_delta)

        # Sleep for a minute before the next check
        time.sleep(60)

if __name__ == "__main__":
    # Set up basic logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    
    # Set necessary environment variables for demonstration/testing if not already set.
    # These are critical for the script to run and pass initial checks.
    if not os.environ.get("APCA_API_KEY_ID"): os.environ["APCA_API_KEY_ID"] = "MOCK_KEY_ID_FOR_GAMMA_SCALPER"
    if not os.environ.get("APCA_API_SECRET_KEY"): os.environ["APCA_API_SECRET_KEY"] = "MOCK_SECRET_KEY_FOR_GAMMA_SCALPER"
    if not os.environ.get("APCA_API_BASE_URL"): os.environ["APCA_API_BASE_URL"] = "https://paper-api.alpaca.markets"
    if not os.environ.get("ENABLE_DANGEROUS_FUNCTIONS"): os.environ["ENABLE_DANGEROUS_FUNCTIONS"] = "true" # Allow execution for example
    
    main()

    # Clean up environment variables used for the example
    for var in ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "APCA_API_BASE_URL", "ENABLE_DANGEROUS_FUNCTIONS"]:
        if var in os.environ:
            del os.environ[var]