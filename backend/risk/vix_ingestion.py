"""
VIX (Volatility Index) Data Ingestion Service.

This service fetches VIX data from market data providers and stores it in Firestore
for use by the VIX Guard circuit breaker.

The VIX is the CBOE Volatility Index, which measures market expectation of near-term
volatility conveyed by S&P 500 stock index option prices.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VIXIngestionService:
    """
    Service for ingesting VIX data into Firestore.
    
    This service can fetch VIX data from multiple sources:
    1. Alpaca (primary)
    2. Yahoo Finance (fallback)
    3. Manual override (for testing)
    """
    
    def __init__(self, db_client: Any = None, alpaca_client: Any = None):
        """
        Initialize the VIX ingestion service.
        
        Args:
            db_client: Firestore client for storing VIX data
            alpaca_client: Alpaca REST client for fetching market data
        """
        self.db = db_client
        self.alpaca = alpaca_client
        self._last_fetch_time: Optional[datetime] = None
        self._last_vix_value: Optional[float] = None
    
    async def fetch_and_store_vix(self) -> Optional[float]:
        """
        Fetch current VIX value and store it in Firestore.
        
        Returns:
            Current VIX value or None if fetch failed
        """
        try:
            # Try multiple sources in order of preference
            vix_value = None
            
            # 1. Try Alpaca first
            if self.alpaca is not None:
                vix_value = await self._fetch_vix_from_alpaca()
            
            # 2. Fallback to Yahoo Finance if Alpaca fails
            if vix_value is None:
                vix_value = await self._fetch_vix_from_yahoo()
            
            if vix_value is None:
                logger.error("Failed to fetch VIX from all sources")
                return None
            
            # Store in Firestore
            await self._store_vix_value(vix_value)
            
            # Update cache
            self._last_vix_value = vix_value
            self._last_fetch_time = datetime.now(timezone.utc)
            
            logger.info(f"Successfully fetched and stored VIX: {vix_value}")
            return vix_value
            
        except Exception as e:
            logger.error(f"Error in fetch_and_store_vix: {e}", exc_info=True)
            return None
    
    async def _fetch_vix_from_alpaca(self) -> Optional[float]:
        """
        Fetch VIX from Alpaca market data API.
        
        Returns:
            VIX value or None if fetch failed
        """
        if self.alpaca is None:
            return None
        
        try:
            # VIX symbol varies by provider
            # Alpaca uses VIX for the CBOE Volatility Index
            # Some providers use ^VIX or $VIX
            symbols = ["VIX", "^VIX", "$VIX"]
            
            for symbol in symbols:
                try:
                    # Get latest trade or bar for VIX
                    bars = self.alpaca.get_bars(
                        symbol,
                        "1Min",
                        limit=1
                    )
                    
                    if bars and len(bars) > 0:
                        latest_bar = bars[-1]
                        vix_value = float(latest_bar.c)  # Close price
                        logger.info(f"Fetched VIX from Alpaca using symbol {symbol}: {vix_value}")
                        return vix_value
                        
                except Exception as symbol_error:
                    logger.debug(f"Symbol {symbol} not found in Alpaca: {symbol_error}")
                    continue
            
            logger.warning("Could not fetch VIX from Alpaca with any symbol variant")
            return None
            
        except Exception as e:
            logger.error(f"Error fetching VIX from Alpaca: {e}", exc_info=True)
            return None
    
    async def _fetch_vix_from_yahoo(self) -> Optional[float]:
        """
        Fetch VIX from Yahoo Finance as a fallback.
        
        Returns:
            VIX value or None if fetch failed
        """
        try:
            # Use yfinance library if available
            import yfinance as yf
            
            ticker = yf.Ticker("^VIX")
            data = ticker.history(period="1d", interval="1m")
            
            if data.empty:
                logger.warning("No VIX data from Yahoo Finance")
                return None
            
            # Get the most recent close price
            vix_value = float(data['Close'].iloc[-1])
            logger.info(f"Fetched VIX from Yahoo Finance: {vix_value}")
            return vix_value
            
        except ImportError:
            logger.warning("yfinance library not installed, skipping Yahoo Finance fallback")
            return None
        except Exception as e:
            logger.error(f"Error fetching VIX from Yahoo Finance: {e}", exc_info=True)
            return None
    
    async def _store_vix_value(self, vix_value: float) -> None:
        """
        Store VIX value in Firestore.
        
        Args:
            vix_value: Current VIX value to store
        """
        if self.db is None:
            logger.error("Cannot store VIX: no database client")
            return
        
        try:
            doc_data = {
                "current_value": vix_value,
                "updated_at": datetime.now(timezone.utc),
                "source": "alpaca",  # or detected source
            }
            
            # Store at systemStatus/vix_data
            self.db.collection("systemStatus").document("vix_data").set(
                doc_data, merge=True
            )
            
            # Also store historical data point
            self.db.collection("systemStatus").document("vix_data").collection(
                "history"
            ).add({
                "value": vix_value,
                "timestamp": datetime.now(timezone.utc),
            })
            
            logger.info(f"Stored VIX value in Firestore: {vix_value}")
            
        except Exception as e:
            logger.error(f"Error storing VIX in Firestore: {e}", exc_info=True)
    
    def get_cached_vix(self) -> Optional[float]:
        """
        Get the most recently cached VIX value.
        
        Returns:
            Cached VIX value or None if no cache
        """
        return self._last_vix_value
    
    async def manual_set_vix(self, vix_value: float) -> None:
        """
        Manually set VIX value (useful for testing).
        
        Args:
            vix_value: VIX value to set
        """
        logger.info(f"Manually setting VIX to {vix_value}")
        await self._store_vix_value(vix_value)
        self._last_vix_value = vix_value
        self._last_fetch_time = datetime.now(timezone.utc)


def create_vix_ingestion_service(
    db_client: Any = None,
    alpaca_client: Any = None,
) -> VIXIngestionService:
    """
    Factory function to create a VIX ingestion service.
    
    Args:
        db_client: Firestore client
        alpaca_client: Alpaca REST client
    
    Returns:
        Configured VIXIngestionService instance
    """
    return VIXIngestionService(db_client=db_client, alpaca_client=alpaca_client)
