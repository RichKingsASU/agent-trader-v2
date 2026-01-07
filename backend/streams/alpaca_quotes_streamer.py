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
from backend.observability.logger import intent_start, intent_end, log_event

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

_batch_last_log_ts = 0.0
_batch_count = 0

async def quote_data_handler(data):
    """Handler for incoming quote data."""
    logging.info(f"Received quote for {data.symbol}: Bid={data.bid_price}, Ask={data.ask_price}")

    # Intent point: data batch received (rate-limited; avoid per-tick spam).
    global _batch_last_log_ts, _batch_count
    _batch_count += 1
    now = asyncio.get_event_loop().time()
    if (now - _batch_last_log_ts) >= 10.0:
        _batch_last_log_ts = now
        ctx = intent_start(
            "data_batch_received",
            "Received quote updates from Alpaca stream.",
            payload={"batch_count": _batch_count, "sample_symbol": getattr(data, "symbol", None)},
        )
        intent_end(ctx, "success")
        _batch_count = 0
    
    emit_ctx = None
    try:
        session = get_market_session(datetime.now(timezone.utc))
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                emit_ctx = intent_start(
                    "marketdata_emit",
                    "Persist live quote to downstream store.",
                    payload={"symbol": data.symbol, "destination": "postgres", "table": "public.live_quotes"},
                )
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
                intent_end(emit_ctx, "success")
    except psycopg2.Error as e:
        logging.error(f"Database error while handling quote for {data.symbol}: {e}")
        if emit_ctx is None:
            emit_ctx = intent_start(
                "marketdata_emit",
                "Persist live quote to downstream store.",
                payload={"symbol": getattr(data, "symbol", None), "destination": "postgres", "table": "public.live_quotes"},
            )
        intent_end(emit_ctx, "failure", error=e)

async def main():
    """Main function to start the quote streamer."""
    # Intent point: startup / connect attempt.
    startup_ctx = intent_start(
        "subscription_connect_attempt",
        "Initialize Alpaca StockDataStream and subscribe to quote symbols.",
        payload={"feed": "IEX", "symbols": SYMBOLS, "symbols_count": len(SYMBOLS)},
    )
    try:
        wss_client = StockDataStream(API_KEY, SECRET_KEY, feed=DataFeed.IEX)

        logging.info(f"Subscribing to quotes for: {SYMBOLS}")
        wss_client.subscribe_quotes(quote_data_handler, *SYMBOLS)
        intent_end(startup_ctx, "success")

        await wss_client.run()
    except Exception as e:
        intent_end(startup_ctx, "failure", error=e)
        raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Streamer stopped by user.")
    except Exception as e:
        logging.error(f"Streamer crashed: {e}")
        log_event("streamer_crashed", level="ERROR")