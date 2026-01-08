
import os
import datetime
import alpaca_trade_api as tradeapi
import yfinance as yf

# --- Configuration ---
from backend.config.alpaca_env import load_alpaca_auth_env

_auth = load_alpaca_auth_env()
# --- Initialize Alpaca API ---
api = tradeapi.REST(
    key_id=_auth.api_key_id,
    secret_key=_auth.api_secret_key,
    base_url=_auth.api_base_url,
    api_version="v2",
)

# --- Strategy Parameters ---
DELTA_THRESHOLD = 0.15
STOP_LOSS_PERCENTAGE = 0.20
EXIT_TIME_ET = datetime.time(15, 45)

def get_spy_200_sma():
    """Fetches the 200-day SMA for SPY."""
    spy = yf.Ticker("SPY")
    hist = spy.history(period="220d")
    return hist['Close'].rolling(window=200).mean().iloc[-1]

def regime_filter():
    """Checks if SPY is above its 200-day SMA."""
    spy_price = yf.Ticker("SPY").history(period="1d")['Close'].iloc[-1]
    sma_200 = get_spy_200_sma()
    return spy_price > sma_200

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
    pass

def check_stop_loss():
    """
    Checks if the 20% drawdown stop-loss has been hit.
    This is a placeholder function.
    """
    account = api.get_account()
    # This is a simplified example. A real implementation would track the
    # portfolio value over time and compare it to the initial value for the day.
    # For now, we'll assume the initial value was the previous day's closing value.
    initial_value = float(account.last_equity)
    current_value = float(account.equity)
    drawdown = (initial_value - current_value) / initial_value
    if drawdown >= STOP_LOSS_PERCENTAGE:
        print(f"Stop-loss of {STOP_LOSS_PERCENTAGE * 100}% hit. Liquidating positions.")
        api.close_all_positions()

def main():
    """Main function for the Gamma Scalper strategy."""
    print("Starting 0DTE Gamma Scalper Strategy...")

    if not regime_filter():
        print("Regime filter not met (SPY is not above 200-day SMA). Exiting.")
        return

    while True:
        now_et = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5))).time()

        if now_et >= EXIT_TIME_ET:
            print(f"Exit time of {EXIT_TIME_ET} reached. Liquidating positions.")
            api.close_all_positions()
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
    main()
