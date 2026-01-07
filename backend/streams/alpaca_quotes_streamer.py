import os
import asyncio
import logging
from datetime import datetime, timezone
import psycopg2
from alpaca.data.live.stock import StockDataStream
from alpaca.data.enums import DataFeed

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from backend.streams.alpaca_env import load_alpaca_env
from backend.utils.session import get_market_session
from backend.common.marketdata_heartbeat import update_last_tick

LAST_MARKETDATA_TS_UTC: datetime | None = None
LAST_MARKETDATA_SOURCE: str = "alpaca_quotes_streamer"


def get_last_marketdata_ts() -> datetime | None:
    return LAST_MARKETDATA_TS_UTC


def _mark_marketdata_seen(ts: datetime | None = None) -> None:
    """
    Updates the in-process marketdata freshness marker.
    This is intentionally lightweight and best-effort.
    """
    global LAST_MARKETDATA_TS_UTC
    if ts is None:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    LAST_MARKETDATA_TS_UTC = ts.astimezone(timezone.utc)


try:
    alpaca = load_alpaca_env()
    API_KEY = alpaca.key_id
    SECRET_KEY = alpaca.secret_key
    DB_URL = os.getenv("DATABASE_URL")
    if not DB_URL:
        raise KeyError("DATABASE_URL")
    SYMBOLS = [s.strip() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",") if s.strip()]
except KeyError as e:
    logging.error(f"FATAL: Missing required environment variable: {e}")
    exit(1)

async def quote_data_handler(data):
    """Handler for incoming quote data."""
    _mark_marketdata_seen()
    logging.info(f"Received quote for {data.symbol}: Bid={data.bid_price}, Ask={data.ask_price}")

    # Heartbeat producer: update whenever we receive a live quote event.
    # Prefer the provider timestamp if present; fall back to "now".
    provider_ts = getattr(data, "timestamp", None)
    if isinstance(provider_ts, datetime):
        update_last_tick(provider_ts)
    else:
        update_last_tick()
    
    try:
        session = get_market_session(datetime.now(timezone.utc))
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise RuntimeError("Missing required env var: DATABASE_URL")
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.live_quotes (
                        symbol, bid_price, bid_size, ask_price, ask_size, last_update_ts, session
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                    ON CONFLICT (symbol) DO UPDATE SET
                        bid_price = EXCLUDED.bid_price,
                        bid_size = EXCLUDED.bid_size,
                        ask_price = EXCLUDED.ask_price,
                        ask_size = EXCLUDED.ask_size,
                        last_update_ts = NOW(),
                        session = EXCLUDED.session;
                    """,
                    (data.symbol, data.bid_price, data.bid_size, data.ask_price, data.ask_size, session)
                )
    except psycopg2.Error as e:
        logging.error(f"Database error while handling quote for {data.symbol}: {e}")

async def main():
    """Main function to start the quote streamer."""
    alpaca = load_alpaca_env()
    wss_client = StockDataStream(alpaca.key_id, alpaca.secret_key, feed=DataFeed.IEX)
    symbols = _symbols_from_env()
    
    logging.info(f"Subscribing to quotes for: {symbols}")
    if not symbols:
        raise RuntimeError("ALPACA_SYMBOLS resolved to empty list")
    wss_client.subscribe_quotes(quote_data_handler, *symbols)
    
    await wss_client.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Streamer stopped by user.")
    except Exception as e:
        logging.error(f"Streamer crashed: {e}")