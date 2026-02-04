# ~/agenttrader_v2/functions/whale_consolidator.py

import os
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Standardize on alpaca-py
# Remove direct import of alpaca_trade_api
# import alpaca_trade_api as tradeapi
from alpaca.trading.client import TradingClient
from alpaca.data.live.stream import DataStream # Import DataStream for live data
from alpaca.common.exceptions import APIError
from firebase_admin import credentials, firestore, initialize_app

from functions.utils.apca_env import assert_paper_alpaca_base_url

"""
Strategy VIII: Institutional Order Flow (Whale Consolidator)

- Logic: Ingests an options feed to identify 'Sweep Orders' (fragmented orders).
- Filter 1 (Aggression): Isolates trades executed at or above the 'Ask Side'.
- Filter 2 (Institutional Size): Flags orders with total premium > $100,000.
- Filter 3 (High-Conviction): Flags if Volume > Open Interest (Vol/OI ratio > 1).
- Orchestration: If >5 Sweeps occur on the same ticker within 60 seconds, 
  broadcasts a 'Whale Cluster Alert' to Firestore.
"""

# --- Configuration ---
PREMIUM_THRESHOLD = 100000.0
CLUSTER_SWEEP_COUNT = 5
CLUSTER_TIME_WINDOW_SECONDS = 60
SYMBOLS_TO_TRACK = ['SPY', 'QQQ', 'TSLA', 'AAPL', 'AMZN', 'NVDA'] # Example symbols

class WhaleConsolidator:
    """
    Connects to an options data stream to detect and consolidate large, 
    aggressive "whale" trades, posting alerts to Firestore when a cluster
    of such trades is detected.
    """
    def __init__(self):
        """
        Initializes the Alpaca API, Firestore client, and internal state for tracking.
        """
        # --- API and DB Initialization ---
        try:
            base_url = assert_paper_alpaca_base_url(
                os.environ.get("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"
            )
            self.api = TradingClient(
                key_id=os.environ.get('APCA_API_KEY_ID'),
                secret_key=os.environ.get('APCA_API_SECRET_KEY'),
                base_url=base_url
            )
            
            # Note: This script is deployed in 'venv_ingest', which requires firebase-admin.
            # Make sure it's installed: functions/venv_ingest/bin/pip install firebase-admin
            if not os.path.exists('serviceAccountKey.json'):
                 raise FileNotFoundError("serviceAccountKey.json not found. Firestore cannot be initialized.")
            cred = credentials.Certificate("serviceAccountKey.json")
            # Ensure Firebase app is initialized only once
            if not firebase_admin._apps:
                initialize_app(cred)
            self.db = firestore.client()
            print("✅ Alpaca API (TradingClient) and Firestore client initialized successfully.")

        except FileNotFoundError as e:
            print(f"🔥 Initialization Error: {e}")
            self.api = None
            self.db = None
        except APIError as e:
            print(f"🔥 Alpaca API Error during initialization: {e.message}")
            self.api = None
            self.db = None
        except Exception as e:
            print(f"🔥 An unexpected error occurred during initialization: {e}")
            self.api = None
            self.db = None

        # --- Internal State ---
        self.latest_quotes = {}
        self.open_interest_cache = {}
        self.recent_sweeps = defaultdict(list) # Stores timestamps of recent sweeps per symbol
        self.running = False
        self.stream_conn = None

    async def _get_open_interest(self, option_symbol: str) -> int:
        """
        Fetches and caches the open interest for a given option contract.
        In a production system, this would be updated daily.
        
        Note: Alpaca API v2 does not directly provide OI for options via REST or streams.
        This function is a placeholder and would require an external data source for real OI.
        """
        if option_symbol not in self.open_interest_cache:
            try:
                # Placeholder: Defaulting to a mock value.
                # A real implementation would query a data source for actual OI.
                self.open_interest_cache[option_symbol] = 1000 
                logger.debug(f"Fetched (mock) Open Interest for {option_symbol}: {self.open_interest_cache[option_symbol]}")
            except Exception as e:
                logger.warning(f"Could not fetch Open Interest for {option_symbol}: {e}")
                self.open_interest_cache[option_symbol] = 0 # Default to 0 on failure
        
        return self.open_interest_cache[option_symbol]

    async def _handle_quote(self, quote):
        """Callback to store the latest quote for an option."""
        # For alpaca-py, the quote object might have different attributes.
        # Assuming `symbol` and `askprice` are accessible.
        symbol = quote.symbol if hasattr(quote, 'symbol') else quote.get('S')
        ask_price = quote.askprice if hasattr(quote, 'askprice') else quote.get('a')
        
        if symbol and ask_price is not None:
            self.latest_quotes[symbol] = {'askprice': ask_price}
            # logger.debug(f"Stored quote for {symbol}: Ask={ask_price}") # Too verbose for default logging
        else:
            logger.warning(f"Received incomplete quote data: {quote}")

    async def _handle_trade(self, trade):
        """
        Core logic to process each trade and apply filters.
        """
        # For alpaca-py, trade object attributes might differ from tradeapi.
        # Assuming 'symbol', 'price', 'size', 'conditions' are accessible.
        option_symbol = trade.symbol if hasattr(trade, 'symbol') else trade.get('S')
        trade_price = trade.price if hasattr(trade, 'price') else trade.get('p')
        trade_size = trade.size if hasattr(trade, 'size') else trade.get('s')
        
        if not option_symbol or trade_price is None or trade_size is None:
            logger.warning(f"Received incomplete trade data: {trade}")
            return

        # Heuristic to get underlying symbol from option symbol.
        # This is fragile and depends heavily on symbol naming conventions.
        # A more robust solution would parse option details from the trade object itself if available.
        underlying = option_symbol # Fallback if parsing fails
        if option_symbol.startswith('O:'): # Example format for some APIs
             parts = option_symbol[2:].split('_') # e.g. O:SPY_20260207C00450000
             if len(parts) > 0:
                 underlying = parts[0][:3] # Heuristic: first 3 chars for SPY, QQQ etc.
        elif any(c.isdigit() for c in option_symbol): # Look for patterns like SPY260207C00450000
            # Basic attempt to extract underlying if it's prefix before date/strike
            for i in range(len(option_symbol)):
                if option_symbol[i].isdigit():
                    underlying = option_symbol[:i]
                    break
        
        # --- Pre-computation ---
        latest_quote = self.latest_quotes.get(option_symbol)
        if not latest_quote:
            # logger.debug(f"No quote data for {option_symbol}, skipping trade.")
            return # Cannot process without a corresponding quote for ask price
        
        ask_price = latest_quote.get('askprice')
        if ask_price is None:
            logger.warning(f"Latest quote for {option_symbol} has no ask price.")
            return

        premium = trade_price * trade_size * 100 # 1 contract = 100 shares
        
        # --- Filter 1: Aggression (Ask Side) ---
        # Check if trade price is at or above the ask price from the latest quote
        is_aggressive = trade_price >= ask_price
        if not is_aggressive:
            # logger.debug(f"Trade {trade.id} on {option_symbol} not aggressive (price {trade_price} < ask {ask_price}).")
            return

        # --- Filter 2: Institutional Size ---
        is_institutional = premium > PREMIUM_THRESHOLD
        if not is_institutional:
            # logger.debug(f"Trade {trade.id} on {option_symbol} below institutional size threshold (${premium:,.2f} < ${PREMIUM_THRESHOLD:,.2f}).")
            return

        # --- Filter 3: High-Conviction (Vol/OI Ratio) ---
        # Note: Daily volume is not available on a per-trade basis from streams.
        # We will use the trade size as a proxy for this demonstration.
        # A robust solution would require a separate volume tracking mechanism or access to OI data.
        open_interest = await self._get_open_interest(option_symbol)
        # Use trade size as a proxy for volume in this context.
        is_high_conviction = open_interest > 0 and trade_size > open_interest
        if not is_high_conviction:
            # logger.debug(f"Trade {trade.id} on {option_symbol} not high conviction (Size {trade_size} <= OI {open_interest}).")
            return

        # --- Orchestration: Whale Cluster Alert ---
        print(f"🐋 Whale Sweep Detected for {underlying}: ${premium:,.2f} Premium for {option_symbol}")
        await self._check_for_cluster(underlying)
        
    async def _check_for_cluster(self, symbol: str):
        """
        Checks for a cluster of sweeps and broadcasts an alert if criteria are met.
        """
        now = datetime.now()
        
        # Add current sweep timestamp
        self.recent_sweeps[symbol].append(now)
        
        # Remove old timestamps
        time_window = now - timedelta(seconds=CLUSTER_TIME_WINDOW_SECONDS)
        self.recent_sweeps[symbol] = [ts for ts in self.recent_sweeps[symbol] if ts > time_window]
        
        # Check for cluster
        if len(self.recent_sweeps[symbol]) >= CLUSTER_SWEEP_COUNT: # Use >= as per original logic
            print(f"🚨🚨 WHALE CLUSTER ALERT for {symbol}! {len(self.recent_sweeps[symbol])} sweeps detected in {CLUSTER_TIME_WINDOW_SECONDS}s. 🚨🚨")
            await self._broadcast_alert(symbol)
            # Clear sweeps for this symbol to avoid repeat alerts within the same cluster detection window
            self.recent_sweeps[symbol] = []

    async def _broadcast_alert(self, symbol: str):
        """
        Writes a "Whale Cluster Alert" to the Firestore database.
        This is linked to the 'Analyst Agent'.
        """
        if not self.db:
            logger.warning("Firestore client not initialized. Cannot broadcast alert.")
            return

        doc_ref = self.db.collection('whaleClusterAlerts').document()
        alert_data = {
            "symbol": symbol,
            "timestamp": datetime.now(),
            "detected_sweeps": CLUSTER_SWEEP_COUNT + 1, # Number of sweeps that triggered alert
            "time_window_seconds": CLUSTER_TIME_WINDOW_SECONDS,
            "message": f"High-conviction institutional activity detected in {symbol}."
        }
        try:
            # Firestore operations are typically synchronous, wrap in to_thread if needed in async context
            # await asyncio.to_thread(doc_ref.set, alert_data) # Correct async usage
            doc_ref.set(alert_data) # Using sync set for simplicity if not in heavily async context
            print(f"✅ Firestore Alert broadcasted for {symbol}")
        except Exception as e:
            logger.error(f"Failed to broadcast alert to Firestore for {symbol}: {e}")

    async def run(self):
        """
        Starts the websocket stream to listen for options trades and quotes using alpaca-py DataStream.
        """
        if not self.api:
            logger.error("Alpaca API client not initialized. Cannot start data stream.")
            return

        logger.info("🚀 WHALE ENGINE LIVE: Connecting to options data stream...")
        base_url = assert_paper_alpaca_base_url(
            os.environ.get("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"
        )
        
        # Use DataStream from alpaca.data.live.stream for WebSocket connections
        try:
            stream = DataStream(
                key_id=os.environ.get('APCA_API_KEY_ID'),
                secret_key=os.environ.get('APCA_API_SECRET_KEY'),
                base_url=base_url,
                # data_feed='option' # Specify data feed if necessary (e.g., 'option' for options)
                # Other parameters like reconnect_attempts, etc. might be configurable
            )

            # Subscribe to trades and quotes for the symbols.
            # The subscription format for options might be different in alpaca-py.
            # Common pattern: 'T.<symbol>' for trades, 'Q.<symbol>' for quotes.
            # For options, it might involve contract symbols if available, or underlying + option type.
            # Assuming we need to subscribe to trades and quotes for the underlying symbols to get option data.
            # This part needs verification with alpaca-py documentation for options streams.
            
            # Example for subscribing to trades and quotes for underlying symbols
            # Real options symbol subscription might look like 'OPTION.<symbol>' or specific contract IDs.
            # For demonstration, using generic trade/quote subscriptions.
            stream.subscribe_trades(self._handle_trade, *[f'T.{s}' for s in SYMBOLS_TO_TRACK])
            stream.subscribe_quotes(self._handle_quote, *[f'Q.{s}' for s in SYMBOLS_TO_TRACK])
            
            logger.info("Subscribed to trades and quotes. Running stream...")
            self.running = True
            await stream.run() # This method manages the connection lifecycle.

        except APIError as e:
            logger.error(f"Alpaca API error during stream setup: {e.message}")
            self.running = False
        except Exception as e:
            logger.error(f"Error setting up or running WebSocket stream: {e}", exc_info=True)
            self.running = False
            raise
        finally:
            await self.stop() # Ensure cleanup

    async def stop(self):
        """ Gracefully stops the stream connection. """
        logger.info("Stopping Whale Consolidator...")
        self.running = False
        if self.stream_conn: # If stream object is accessible and has a stop method
            try:
                await self.stream_conn.stop() # Placeholder for stopping the stream
                logger.info("WebSocket stream connection stopped.")
            except Exception as e:
                logger.error(f"Error stopping WebSocket connection: {e}")
        logger.info("Whale Consolidator stopped.")


if __name__ == "__main__":
    # This script requires the following environment variables to be set:
    # APCA_API_KEY_ID, APCA_API_SECRET_KEY
    # It also requires 'serviceAccountKey.json' for Firestore. 
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    
    consolidator = WhaleConsolidator()
    if not (consolidator.api and consolidator.db):
        print("FATAL: Initialization failed. Exiting.")
        sys.exit(1)

    try:
        asyncio.run(consolidator.run())
    except KeyboardInterrupt:
        print("\n📈 Whale Engine shutting down.")
    except Exception as e:
        logger.error(f"Main execution loop encountered an error: {e}", exc_info=True)
    finally:
        # Ensure cleanup is called
        asyncio.run(consolidator.stop())
