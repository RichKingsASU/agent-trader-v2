"""
Real-time market data feed using Alpaca WebSocket API.

Streams minute bars for target tickers and upserts them into Firestore.
Includes connection retry logic and proper error handling.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

import alpaca_trade_api as tradeapi
import firebase_admin
from firebase_admin import firestore

logger = logging.getLogger(__name__)


def _get_firestore() -> firestore.Client:
    """Initialize and return Firestore client."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return firestore.client()


def _get_alpaca_credentials() -> Dict[str, str]:
    """
    Retrieve Alpaca credentials from environment variables.
    
    Returns:
        Dictionary with key_id, secret_key, and base_url.
        
    Raises:
        ValueError: If required credentials are missing.
    """
    key_id = os.environ.get("ALPACA_KEY_ID") or os.environ.get("APCA_API_KEY_ID")
    secret_key = os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY")
    
    if not key_id or not secret_key:
        raise ValueError(
            "Missing Alpaca credentials. Set ALPACA_KEY_ID/ALPACA_SECRET_KEY "
            "or APCA_API_KEY_ID/APCA_API_SECRET_KEY."
        )
    
    base_url = (
        os.environ.get("APCA_API_BASE_URL")
        or os.environ.get("ALPACA_API_BASE_URL")
        or "https://api.alpaca.markets"
    )
    
    return {
        "key_id": key_id,
        "secret_key": secret_key,
        "base_url": base_url,
    }


def _get_target_symbols() -> List[str]:
    """
    Get target ticker symbols from environment or use defaults.
    
    Returns:
        List of ticker symbols to stream.
    """
    symbols_str = os.environ.get("TICKER_SYMBOLS", "AAPL,NVDA,TSLA")
    return [s.strip().upper() for s in symbols_str.split(",") if s.strip()]


class TickerService:
    """
    Real-time market data service that streams minute bars from Alpaca
    and stores them in Firestore.
    """
    
    def __init__(self):
        self.credentials = _get_alpaca_credentials()
        self.symbols = _get_target_symbols()
        self.db = _get_firestore()
        self.conn = None
        self.running = False
        self.max_retries = 5
        self.retry_delay = 5  # seconds
        
    async def _handle_bar(self, bar: Any) -> None:
        """
        Handle incoming minute bar data and upsert to Firestore.
        
        Args:
            bar: Bar data object from Alpaca WebSocket.
        """
        try:
            # Extract bar data
            symbol = bar.symbol if hasattr(bar, 'symbol') else bar.get('S')
            timestamp = bar.timestamp if hasattr(bar, 'timestamp') else bar.get('t')
            
            # Parse timestamp
            if isinstance(timestamp, str):
                bar_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            elif isinstance(timestamp, datetime):
                bar_time = timestamp
            else:
                bar_time = datetime.fromtimestamp(timestamp / 1000000000, tz=timezone.utc)
            
            # Extract OHLCV data
            data = {
                "symbol": symbol,
                "timestamp": bar_time,
                "open": float(bar.open if hasattr(bar, 'open') else bar.get('o', 0)),
                "high": float(bar.high if hasattr(bar, 'high') else bar.get('h', 0)),
                "low": float(bar.low if hasattr(bar, 'low') else bar.get('l', 0)),
                "close": float(bar.close if hasattr(bar, 'close') else bar.get('c', 0)),
                "volume": int(bar.volume if hasattr(bar, 'volume') else bar.get('v', 0)),
                "updatedAt": firestore.SERVER_TIMESTAMP,
            }
            
            logger.info(
                f"Bar received: {symbol} @ {bar_time.isoformat()} "
                f"O:{data['open']:.2f} H:{data['high']:.2f} "
                f"L:{data['low']:.2f} C:{data['close']:.2f} V:{data['volume']}"
            )
            
            # Upsert to Firestore: marketData/{symbol}
            doc_ref = self.db.collection("marketData").document(symbol)
            doc_ref.set(data, merge=True)
            
            logger.info(f"Successfully upserted {symbol} to Firestore")
            
        except Exception as e:
            logger.error(f"Error handling bar data: {e}", exc_info=True)
    
    async def _run_stream(self) -> None:
        """
        Run the WebSocket stream with connection handling.
        
        Raises:
            Exception: If connection fails after max retries.
        """
        retry_count = 0
        
        while self.running and retry_count < self.max_retries:
            try:
                logger.info(
                    f"Starting Alpaca WebSocket stream for symbols: {', '.join(self.symbols)}"
                )
                
                # Create WebSocket connection
                self.conn = tradeapi.Stream(
                    key_id=self.credentials["key_id"],
                    secret_key=self.credentials["secret_key"],
                    base_url=self.credentials["base_url"],
                    data_feed="iex",  # Use IEX feed for real-time data
                )
                
                # Subscribe to minute bars for all symbols
                @self.conn.on_bar(*self.symbols)
                async def on_bar(bar):
                    await self._handle_bar(bar)
                
                # Run the stream
                logger.info("WebSocket connection established, streaming data...")
                await self.conn.run()
                
                # If we reach here, connection was closed
                if self.running:
                    logger.warning("WebSocket connection closed unexpectedly")
                    retry_count += 1
                else:
                    logger.info("WebSocket stream stopped gracefully")
                    break
                    
            except Exception as e:
                retry_count += 1
                logger.error(
                    f"Error in WebSocket stream (attempt {retry_count}/{self.max_retries}): {e}",
                    exc_info=True
                )
                
                if retry_count < self.max_retries and self.running:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    await asyncio.sleep(self.retry_delay)
                    # Exponential backoff
                    self.retry_delay = min(self.retry_delay * 2, 60)
                else:
                    logger.error("Max retries reached or service stopped")
                    raise
    
    async def start(self) -> None:
        """
        Start the ticker service.
        
        This will begin streaming minute bars and storing them in Firestore.
        """
        logger.info("Starting Ticker Service...")
        logger.info(f"Monitoring symbols: {', '.join(self.symbols)}")
        
        self.running = True
        
        try:
            await self._run_stream()
        except Exception as e:
            logger.error(f"Ticker service failed: {e}", exc_info=True)
            raise
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """
        Stop the ticker service gracefully.
        """
        logger.info("Stopping Ticker Service...")
        self.running = False
        
        if self.conn:
            try:
                await self.conn.close()
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Error closing WebSocket connection: {e}")
        
        logger.info("Ticker Service stopped")


async def run_ticker_service() -> None:
    """
    Main entry point to run the ticker service.
    
    This function can be called from a Cloud Function or run standalone.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    service = TickerService()
    
    try:
        await service.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        await service.stop()


if __name__ == "__main__":
    """
    Run the service standalone for testing.
    
    Usage:
        export ALPACA_KEY_ID=your_key_id
        export ALPACA_SECRET_KEY=your_secret_key
        export TICKER_SYMBOLS=AAPL,NVDA,TSLA  # Optional
        python ticker_service.py
    """
    asyncio.run(run_ticker_service())
