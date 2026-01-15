import logging
import os
from datetime import datetime

import psycopg
import requests

from backend.common.secrets import get_secret
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session

logger = logging.getLogger(__name__)

def fetch_latest_quote(*, symbol: str, alpaca: object, api_key: str, secret_key: str):
    """Fetches the latest quote for a symbol from Alpaca."""
    url = f"{alpaca.data_stocks_base_v2}/{symbol}/quotes/latest"
    try:
        r = requests.get(
            url,
            headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key},
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
        db_url = get_secret("DATABASE_URL", required=True)
        conn = psycopg.connect(db_url)
    except psycopg.OperationalError as e:
        logger.critical(
            "Could not connect to database",
            extra={"event_type": "db.connect_failed", "error": str(e)},
        )
        return

    alpaca = load_alpaca_env()
    symbol_to_test = (os.getenv("ALPACA_SYMBOLS", "SPY").split(",")[0] or "SPY").strip().upper()
    quote = fetch_latest_quote(
        symbol=symbol_to_test,
        alpaca=alpaca,
        api_key=alpaca.key_id,
        secret_key=alpaca.secret_key,
    )

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