# ~/agenttrader_v2/functions/whale_consolidator.py

import os
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
import alpaca_trade_api as tradeapi
from alpaca_trade_api.stream import Stream
from firebase_admin import credentials, firestore, initialize_app

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
            self.api = tradeapi.REST(
                key_id=os.environ.get('APCA_API_KEY_ID'),
                secret_key=os.environ.get('APCA_API_SECRET_KEY'),
                base_url=os.environ.get('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')
            )
            
            # Note: This script is deployed in 'venv_ingest', which requires firebase-admin.
            # Make sure it's installed: functions/venv_ingest/bin/pip install firebase-admin
            if not os.path.exists('serviceAccountKey.json'):
                 raise FileNotFoundError("serviceAccountKey.json not found. Firestore cannot be initialized.")
            cred = credentials.Certificate("serviceAccountKey.json")
            initialize_app(cred)
            self.db = firestore.client()
            print("✅ Alpaca API and Firestore client initialized successfully.")

        except Exception as e:
            print(f"🔥 Initialization Error: {e}")
            self.api = None
            self.db = None

        # --- Internal State ---
        self.latest_quotes = {}
        self.open_interest_cache = {}
        self.recent_sweeps = defaultdict(list) # Stores timestamps of recent sweeps per symbol

    async def _get_open_interest(self, option_symbol: str) -> int:
        """
        Fetches and caches the open interest for a given option contract.
        In a production system, this would be updated daily.
        """
        if option_symbol not in self.open_interest_cache:
            try:
                # This is a placeholder for fetching contract details.
                # Alpaca API v2 does not directly provide OI for options contracts via REST.
                # In a real scenario, this data would come from a different data provider.
                # We will simulate it with a default value for the logic to work.
                self.open_interest_cache[option_symbol] = 1000 # Default mock value
            except Exception as e:
                print(f"⚠️ Could not fetch Open Interest for {option_symbol}: {e}")
                self.open_interest_cache[option_symbol] = 0 # Default to 0 on failure
        
        return self.open_interest_cache[option_symbol]

    async def _handle_quote(self, quote):
        """Callback to store the latest quote for an option."""
        self.latest_quotes[quote.symbol] = quote

    async def _handle_trade(self, trade):
        """
        Core logic to process each trade and apply filters.
        """
        option_symbol = trade.symbol
        underlying = option_symbol.rstrip('0123456789')[:-8] # Heuristic to get underlying
        
        # --- Pre-computation ---
        latest_quote = self.latest_quotes.get(option_symbol)
        if not latest_quote:
            return # Cannot process without a corresponding quote

        premium = trade.price * trade.size * 100 # 1 contract = 100 shares
        
        # --- Filter 1: Aggression (Ask Side) ---
        is_aggressive = trade.price >= latest_quote.ask_price
        if not is_aggressive:
            return

        # --- Filter 2: Institutional Size ---
        is_institutional = premium > PREMIUM_THRESHOLD
        if not is_institutional:
            return

        # --- Filter 3: High-Conviction (Vol/OI Ratio) ---
        # Note: Daily volume is not available on a per-trade basis.
        # We will use the trade size as a proxy for this demonstration.
        # A robust solution would require a separate volume tracking mechanism.
        open_interest = await self._get_open_interest(option_symbol)
        is_high_conviction = open_interest > 0 and trade.size > open_interest
        if not is_high_conviction:
            return

        # --- Orchestration: Whale Cluster Alert ---
        print(f"🐋 Whale Sweep Detected for {underlying}: ${premium:,.2f} Premium")
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
        if len(self.recent_sweeps[symbol]) > CLUSTER_SWEEP_COUNT:
            print(f"🚨🚨 WHALE CLUSTER ALERT for {symbol}! 🚨🚨")
            await self._broadcast_alert(symbol)
            # Clear sweeps for this symbol to avoid repeat alerts
            self.recent_sweeps[symbol] = []

    async def _broadcast_alert(self, symbol: str):
        """
        Writes a "Whale Cluster Alert" to the Firestore database.
        This is linked to the 'Analyst Agent'.
        """
        if not self.db:
            return

        doc_ref = self.db.collection('whaleClusterAlerts').document()
        alert_data = {
            "symbol": symbol,
            "timestamp": datetime.now(),
            "detected_sweeps": CLUSTER_SWEEP_COUNT + 1,
            "time_window_seconds": CLUSTER_TIME_WINDOW_SECONDS,
            "message": f"High-conviction institutional activity detected in {symbol}."
        }
        await asyncio.to_thread(doc_ref.set, alert_data)
        print(f"✅ Firestore Alert broadcasted for {symbol}")

    async def run(self):
        """
        Starts the websocket stream to listen for options trades and quotes.
        """
        if not self.api:
            print("🔥 Cannot run Whale Consolidator without API initialization.")
            return

        print("🚀 WHALE ENGINE LIVE: Connecting to options data stream...")
        stream = Stream(
            key_id=os.environ.get('APCA_API_KEY_ID'),
            secret_key=os.environ.get('APCA_API_SECRET_KEY'),
            base_url=os.environ.get('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets'),
            data_feed='opra' # OPRA feed for options
        )

        # Subscribe to trades and quotes for the symbols
        for symbol in SYMBOLS_TO_TRACK:
            stream.subscribe_trades(self._handle_trade, f'T.{symbol}')
            stream.subscribe_quotes(self._handle_quote, f'Q.{symbol}')
        
        await stream.run()


if __name__ == "__main__":
    # This script requires the following environment variables to be set:
    # APCA_API_KEY_ID, APCA_API_SECRET_KEY
    # It also requires 'serviceAccountKey.json' for Firestore.
    
    consolidator = WhaleConsolidator()
    try:
        asyncio.run(consolidator.run())
    except KeyboardInterrupt:
        print("\n📈 Whale Engine shutting down.")