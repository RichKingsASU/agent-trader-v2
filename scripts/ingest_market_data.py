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
from backend.config.alpaca_env import load_alpaca_auth_env

def main():
    """
    Fetches the latest 1-minute bar data from Alpaca for a list of symbols
    and upserts it into the market_data_1m table with a session flag.
    """
    # --- Configuration (Cloud Shell-safe: env vars only; no .env files) ---
    database_url = os.getenv("DATABASE_URL")
    auth = load_alpaca_auth_env()
    api_key = auth.api_key_id
    secret_key = auth.api_secret_key
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
    
    if not database_url:
        print(f"[{dt.datetime.now().isoformat()}] DATABASE_URL not set; API-only mode (no DB writes).")
        return

    print(f"[{dt.datetime.now().isoformat()}] Upserting {len(records_to_upsert)} records into the database.")

    try:
        try:
            import psycopg  # type: ignore
        except Exception as e:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg is not installed in this environment. "
                "Install it (e.g. pip install psycopg[binary]) to enable DB upserts."
            ) from e

        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                upsert_sql = """
                INSERT INTO public.market_data_1m (ts, symbol, open, high, low, close, volume, session)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ts, symbol) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    session = EXCLUDED.session;
                """
                cur.executemany(upsert_sql, records_to_upsert)
        print(f"[{dt.datetime.now().isoformat()}] Database upsert successful.")
    except Exception as e:
        print(f"[{dt.datetime.now().isoformat()}] ERROR: Database upsert failed: {e}")
        raise

if __name__ == "__main__":
    main()
