# agenttrader/backend/streams/test_live_quote_ingest.py
import os
import requests
import psycopg
from datetime import datetime
from dotenv import load_dotenv

from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session

# --- Environment Configuration ---
load_dotenv() # Load environment variables from .env.local
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("Missing required env var: DATABASE_URL")
alpaca = load_alpaca_env()
API_KEY = alpaca.key_id
SECRET_KEY = alpaca.secret_key
SYMBOLS_STR = os.getenv("ALPACA_SYMBOLS", "SPY") # Test with one symbol for speed
SYMBOLS = [s.strip() for s in SYMBOLS_STR.split(',')]

def fetch_latest_quote(symbol: str):
    """Fetches the latest quote for a symbol from Alpaca."""
    url = f"{alpaca.data_stocks_base_v2}/{symbol}/quotes/latest"
    try:
        r = requests.get(
            url,
            headers={"APCA-API-KEY-ID": API_KEY, "APCA-API-SECRET-KEY": SECRET_KEY},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("quote")
    except requests.RequestException as e:
        print(f"Failed to fetch quote for {symbol}: {e}")
        return None

def main():
    """Fetches a single quote and upserts it to trigger a realtime event."""
    print("--- Running Test Quote Ingest ---")
    try:
        conn = psycopg.connect(DATABASE_URL)
    except psycopg.OperationalError as e:
        print(f"FATAL: Could not connect to database: {e}")
        return

    symbol_to_test = SYMBOLS[0]
    quote = fetch_latest_quote(symbol_to_test)

    if not quote:
        print(f"No quote found for {symbol_to_test}, cannot trigger realtime event.")
        return

    ts = normalize_alpaca_timestamp(quote["t"])
    session = get_market_session(ts)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.live_quotes
              (symbol, ts, bid_price, bid_size, ask_price, ask_size, session)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (symbol) DO UPDATE
              SET ts = EXCLUDED.ts,
                  bid_price = EXCLUDED.bid_price,
                  bid_size = EXCLUDED.bid_size,
                  ask_price = EXCLUDED.ask_price,
                  ask_size = EXCLUDED.ask_size,
                  session = EXCLUDED.session;
            """,
            (
                symbol_to_test,
                ts,
                quote.get("bp", 0),
                quote.get("bs", 0),
                quote.get("ap", 0),
                quote.get("as", 0),
                session,
            ),
        )
    conn.commit()
    conn.close()
    print(f"Upserted test quote for {symbol_to_test} to trigger change.")
    print("--- Finished Test Quote Ingest ---")

if __name__ == "__main__":
    main()