import os
import asyncio
import logging
import psycopg2
from datetime import datetime, timezone
from alpaca.data.live.stock import StockDataStream
from alpaca.data.enums import DataFeed

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from backend.streams.alpaca_env import load_alpaca_env
from backend.utils.session import get_market_session

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
    logging.info(f"Received quote for {data.symbol}: Bid={data.bid_price}, Ask={data.ask_price}")
    
    try:
        session = get_market_session(datetime.now(timezone.utc))
        with psycopg2.connect(DB_URL) as conn:
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
    wss_client = StockDataStream(API_KEY, SECRET_KEY, feed=DataFeed.IEX)
    
    logging.info(f"Subscribing to quotes for: {SYMBOLS}")
    wss_client.subscribe_quotes(quote_data_handler, *SYMBOLS)
    
    await wss_client.run()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Streamer stopped by user.")
    except Exception as e:
        logging.error(f"Streamer crashed: {e}")