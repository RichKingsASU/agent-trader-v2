
import datetime
import time

def get_market_state():
    """
    Determines the current market state (PRE_MARKET, OPEN, POST_MARKET).
    """
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-5))).time()
    market_open = datetime.time(9, 30)
    market_close = datetime.time(16, 0)
    pre_market_open = datetime.time(4, 0)

    if now >= market_open and now < market_close:
        return "OPEN"
    elif now >= pre_market_open and now < market_open:
        return "PRE_MARKET"
    else:
        return "POST_MARKET"

def main():
    """
    Main function for the market clock.
    """
    while True:
        state = get_market_state()
        print(f"Current Market State: {state}")
        # In a real application, you would trigger events or jobs based on the state.
        time.sleep(60)

if __name__ == "__main__":
    main()
