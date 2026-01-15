# agenttrader/scripts/ingest_market_data.py
import os
import sys
import time
import datetime as dt
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

# Correctly import the shared session classifier
# Add backend to path to allow direct execution of this script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.utils.session import get_market_session
from backend.common.timeutils import parse_alpaca_timestamp
from backend.common.alpaca_env import configure_alpaca_env
from backend.common.secrets import get_database_url

def main():
    """
    Fetches the latest 1-minute bar data from Alpaca for a list of symbols
    and upserts it into the market_data_1m table with a session flag.
    """
    # --- Configuration (Cloud Shell-safe: env vars only; no .env files) ---
    database_url = get_database_url(required=True)
    alpaca = configure_alpaca_env(required=True)
    api_key = alpaca.api_key_id
    secret_key = alpaca.api_secret_key
    symbols_str = os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ")
    symbols = [s.strip() for s in symbols_str.split(',')]
    feed = os.getenv("ALPACA_FEED", "iex")
    data_base = os.getenv("ALPACA_DATA_HOST", "https://data.alpaca.markets").rstrip("/")

    print(f"[{dt.datetime.now().isoformat()}] Starting 1-minute bar ingestion for: {symbols}")

    # --- Fetch Data (REST; avoids extra SDK deps in Cloud Shell) ---
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key}
    url = f"{data_base}/v2/stocks/bars"
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "1Min",
        "limit": 1,
        "feed": feed,
        "adjustment": "all",
    }

    last_err: Optional[Exception] = None
    payload: Dict[str, Any] = {}
    for i in range(3):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=30)
            r.raise_for_status()
            payload = r.json()
            last_err = None
            break
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** i, 5))
    if last_err is not None:
        raise last_err

    bars_map: Dict[str, List[Dict[str, Any]]] = payload.get("bars") or {}
    fetched = sum(len(v) for v in bars_map.values())
    print(f"[{dt.datetime.now().isoformat()}] Fetched {fetched} bars from Alpaca.")

    # --- Database Upsert ---
    if not bars_map:
        print(f"[{dt.datetime.now().isoformat()}] No new bars found. Exiting.")
        return

    records_to_upsert: List[Tuple[Any, ...]] = []
    for symbol, bar_list in bars_map.items():
        for bar in bar_list:
            # Alpaca bar JSON keys: t,o,h,l,c,v
            ts = parse_alpaca_timestamp(bar["t"])
            session = get_market_session(ts)
            records_to_upsert.append(
                (
                    ts,
                    symbol,
                    bar.get("o"),
                    bar.get("h"),
                    bar.get("l"),
                    bar.get("c"),
                    bar.get("v"),
                    session,
                )
            )
    
    print(f"[{dt.datetime.now().isoformat()}] Upserting {len(records_to_upsert)} records into the database.")

# Determine the feed to use for runtime.
# Priority: 1. equities_feed, 2. options_feed (if only one found, treat as equities), 3. default 'iex'.
feed = equities_feed
if not feed and options_feed:
    feed = options_feed # Treat options feed as equities if it's the only one found.

# If feed is still empty after checking secrets, use default 'iex'.
# Removed fallback to os.getenv("ALPACA_FEED", ...) as per requirement.
feed = feed or "iex"
feed = str(feed).strip().lower() or "iex" # Ensure it's lowercased and not empty

data_base = get_secret("ALPACA_DATA_HOST", default="https://data.alpaca.markets")
data_base = data_base.rstrip("/")