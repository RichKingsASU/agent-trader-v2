import os
import sys
import subprocess
import psycopg2
from decimal import Decimal

# --- Configuration ---
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    print("Error: DATABASE_URL environment variable not set.")
    sys.exit(1)

def get_last_n_bars(symbol: str, n: int, session: str = 'REGULAR'):
    """Fetches the last N bars for a symbol from the database."""
    print(f"Fetching last {n} bars for {symbol} in session {session}...")
    try:
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ts, open, high, low, close, volume
                    FROM public.market_data_1m
                    WHERE symbol = %s AND session = %s
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    (symbol, session, n)
                )
                return cur.fetchall()
    except psycopg2.Error as e:
        print(f"Database error: {e}")
        return []

def run_strategy(symbol: str, execute: bool = False):
    """Runs a naive strategy: if the last close is higher than the previous, signal a buy."""
    bars = get_last_n_bars(symbol, 2)
    if len(bars) < 2:
        print(f"Not enough data to run strategy for {symbol}.")
        return

    latest_bar = bars[0]
    previous_bar = bars[1]

    latest_close = Decimal(latest_bar[4])
    previous_close = Decimal(previous_bar[4])

    print(f"Latest close for {symbol}: {latest_close}")
    print(f"Previous close for {symbol}: {previous_close}")

    if latest_close > previous_close:
        print(f"Strategy signal: BUY {symbol}")
        if execute:
            print("Executing trade...")
            try:
                subprocess.run(
                    ["python", "backend/streams/manual_paper_trade.py", symbol, "buy", "1"],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                print(f"Error executing trade: {e}")
        else:
            print("Dry run: no trade executed. Use --execute to place a real paper trade.")
    else:
        print(f"Strategy signal: HOLD {symbol}")

def main():
    """Main function to run the strategy driver."""
    symbol = "SPY"  # Default to SPY
    execute = "--execute" in sys.argv

    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        symbol = sys.argv[1].upper()

    print(f"Running naive strategy for {symbol}...")
    run_strategy(symbol, execute)

if __name__ == "__main__":
    main()
