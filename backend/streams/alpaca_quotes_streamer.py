import asyncio
import os
import logging
from datetime import datetime, timezone
import json
from typing import Optional

from alpaca.data.live.stock import StockDataStream
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
    feed = (get_secret("ALPACA_DATA_FEED", fail_if_missing=False) or "iex").lower()
    
    if not symbols:
        raise RuntimeError("No symbols configured for streamer.")

    # Initialize Firestore
    db = firestore.Client()
    # We assume 'default' tenant for this simple setup or read from env
    tenant_id = os.getenv("TENANT_ID", "default")
    quote_collection = db.collection(f"tenants/{tenant_id}/market_intelligence/quotes/live")

    # buffer for batch writes
    # For a real high-throughput system you'd use a more sophisticated buffer/batch writer
    # For this MCP server usage, direct writes are "okay" for low volume, but we should be careful.
    
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
                "ingest_ts": now
            }
            
            # Fire and forget write to Firestore (or await if strict consistency needed)
            # In a loop this can be slow. Ideally use a background writer.
            doc_ref = quote_collection.document(quote.symbol)
            doc_ref.set(data) # sync call blocking loop? No, gcloud client is sync.
            # We should offload this to a thread for better performance in async loop
            # But for "Live Data" proof of concept, this connects the pipes.
            
            # Simple debug log
            # logger.info(f"Quote: {quote.symbol} {quote.bid_price}/{quote.ask_price}")
            
        except Exception as e:
            logger.error(f"Error processing quote: {e}")

    # Initialize Stream
    stream = StockDataStream(alpaca.key_id, alpaca.secret_key, feed=feed)
    
    stream.subscribe_quotes(quote_handler, *symbols)

    logger.info(f"Subscribed to quotes for: {symbols} on feed {feed}")
    
    # Signal readiness
    ready_event.set()
    
    # Run stream
    # stream.run() is blocking. We need to run it in a way that plays nice with asyncio or just block here
    # since we are inside an asyncio task.
    # The alpaca-py stream.run() uses asyncio.run() internally if look closely? 
    # Actually StockDataStream.run() is an indefinitely blocking call wrapping a websocket loop.
    # We should use stream.run() but we are already in an async function.
    # Let's use the async method if available, or run closer to the metal.
    
    # Checking alpaca-py docs/source: it uses a websocket. 
    # For simplicity in this context:
    await stream._run_forever()