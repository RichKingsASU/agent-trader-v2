# agenttrader/backend/streams/test_live_quote_ingest.py
import os
import requests
import psycopg
from datetime import datetime
import logging

from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session
from backend.common.logging import init_structured_logging
from backend.common.alpaca_env import configure_alpaca_env
from backend.common.secrets import get_database_url

init_structured_logging(service="test-live-quote-ingest")
logger = logging.getLogger(__name__)

# --- Environment Configuration ---
_ = configure_alpaca_env(required=True)
DATABASE_URL = get_database_url(required=True)
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
        logger.exception(
            "Failed to fetch quote",
            extra={"event_type": "alpaca.quote_fetch_failed", "symbol": symbol, "error": str(e)},
        )
        return None

def main():
    """Fetches a single quote and upserts it to trigger a realtime event."""
    logger.info("Running test quote ingest", extra={"event_type": "test_quote_ingest.start"})
    try:
        conn = psycopg.connect(DATABASE_URL)
    except psycopg.OperationalError as e:
        logger.critical(
            "Could not connect to database",
            extra={"event_type": "db.connect_failed", "error": str(e)},
        )
        return

    symbol_to_test = SYMBOLS[0]
    quote = fetch_latest_quote(symbol_to_test)

    if not quote:
        logger.warning(
            "No quote found; cannot trigger realtime event",
            extra={"event_type": "alpaca.no_quote", "symbol": symbol_to_test},
        )
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
    logger.info(
        "Upserted test quote to trigger change",
        extra={"event_type": "db.upserted_test_quote", "symbol": symbol_to_test},
    )
    logger.info("Finished test quote ingest", extra={"event_type": "test_quote_ingest.end"})

if __name__ == "__main__":
    main()