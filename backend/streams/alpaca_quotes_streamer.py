import asyncio
import os
import logging
from datetime import datetime, timezone
import json
from typing import Optional

from alpaca.data.live.stock import StockDataStream
from alpaca.data.live.option import OptionDataStream
from alpaca.data.models import Quote
from google.cloud import firestore

from backend.common.secrets import get_secret
from backend.streams.alpaca_env import load_alpaca_env

logger = logging.getLogger(__name__)

# Global state for last tick (used by health checks)
_LAST_MARKETDATA_TS: Optional[datetime] = None

def get_last_marketdata_ts() -> Optional[datetime]:
    return _LAST_MARKETDATA_TS

async def main(ready_event: asyncio.Event) -> None:
    """
    Main entry point for the Alpaca Streamer.
    """
    global _LAST_MARKETDATA_TS
    
    logger.info("Initializing Alpaca Streamer...")
    
    # Load configuration
    alpaca = load_alpaca_env()
    symbols = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",") if s.strip()]
    option_symbols = [s.strip().upper() for s in os.getenv("ALPACA_OPTION_SYMBOLS", "").split(",") if s.strip()]
    feed = (get_secret("ALPACA_DATA_FEED", fail_if_missing=False) or "iex").lower()
    
    if not symbols and not option_symbols:
        logger.warning("No stock or option symbols configured for streamer.")
        ready_event.set()
        return

    # Initialize Firestore
    db = firestore.Client()
    tenant_id = os.getenv("TENANT_ID", "default")
    quote_collection = db.collection(f"tenants/{tenant_id}/market_intelligence/quotes/live")

    async def quote_handler(quote: Quote):
        global _LAST_MARKETDATA_TS
        try:
            now = datetime.now(timezone.utc)
            _LAST_MARKETDATA_TS = now
            
            data = {
                "symbol": quote.symbol,
                "bid_price": quote.bid_price,
                "ask_price": quote.ask_price,
                "bid_size": quote.bid_size,
                "ask_size": quote.ask_size,
                "last_update_ts": quote.timestamp, 
                "ingest_ts": now,
                "asset_class": "us_equity"
            }
            
            doc_ref = quote_collection.document(quote.symbol)
            doc_ref.set(data)
            
        except Exception as e:
            logger.error(f"Error processing stock quote for {quote.symbol}: {e}")

    async def option_quote_handler(quote: Quote):
        global _LAST_MARKETDATA_TS
        try:
            now = datetime.now(timezone.utc)
            _LAST_MARKETDATA_TS = now
            
            data = {
                "symbol": quote.symbol,
                "bid_price": quote.bid_price,
                "ask_price": quote.ask_price,
                "bid_size": quote.bid_size,
                "ask_size": quote.ask_size,
                "last_update_ts": quote.timestamp, 
                "ingest_ts": now,
                "asset_class": "us_option"
            }
            
            doc_ref = quote_collection.document(quote.symbol)
            doc_ref.set(data)
            
        except Exception as e:
            logger.error(f"Error processing option quote for {quote.symbol}: {e}")

    tasks = []

    # Initialize Stock Stream
    if symbols:
        stock_stream = StockDataStream(alpaca.key_id, alpaca.secret_key, feed=feed)
        stock_stream.subscribe_quotes(quote_handler, *symbols)
        logger.info(f"Subscribed to stock quotes: {symbols}")
        tasks.append(stock_stream._run_forever())

    # Initialize Option Stream
    if option_symbols:
        # Note: Option data feed is usually 'sip' or 'opra'. 'iex' doesn't support options.
        # However, for simplicity we try to use the configured feed or default to 'opra'
        option_stream = OptionDataStream(alpaca.key_id, alpaca.secret_key)
        option_stream.subscribe_quotes(option_quote_handler, *option_symbols)
        logger.info(f"Subscribed to option quotes: {option_symbols}")
        tasks.append(option_stream._run_forever())
    
    # Signal readiness
    ready_event.set()
    
    if tasks:
        await asyncio.gather(*tasks)
    else:
        logger.warning("No streaming tasks to run.")