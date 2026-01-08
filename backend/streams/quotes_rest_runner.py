import os, time, logging
from datetime import datetime
from typing import Optional, Dict, Any

import requests
import psycopg2
from psycopg2.extras import execute_values
from tenacity import retry, wait_exponential, stop_after_attempt

from backend.config.alpaca_env import load_alpaca_auth_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session

# --- Standard Header ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("Missing required env var: DATABASE_URL")
auth = None
try:
    auth = load_alpaca_auth_env()
except Exception:
    auth = None
ALPACA_KEY = auth.api_key_id if auth is not None else ""
ALPACA_SEC = auth.api_secret_key if auth is not None else ""
SYMBOLS = os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ").split(",")
FEED = os.getenv("ALPACA_FEED", "iex")
ALPACA_HOST = (os.getenv("ALPACA_DATA_HOST") or "https://data.alpaca.markets").rstrip("/")

session = requests.Session()
if ALPACA_KEY and ALPACA_SEC:
    session.headers.update({
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SEC,
    })
# --- End Standard Header ---

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
def fetch_latest_bar(sym: str) -> Optional[Dict[str, Any]]:
    """Fetch the latest 1-minute bar for `sym` from Alpaca."""
    if not (ALPACA_KEY and ALPACA_SEC):
        logger.warning("ALPACA credentials not set — skipping fetch for %s", sym)
        return None
    try:
        url = f"{ALPACA_HOST}/v2/stocks/{sym}/bars"
        params = {"timeframe": "1Min", "limit": 1, "feed": FEED, "adjustment": "all"}
        r = session.get(url, params=params, timeout=10)
        r.raise_for_status()
        bars = r.json().get("bars", [])
        if not bars:
            return None
        return bars[0]
    except requests.exceptions.RequestException as e:
        logger.error(f"fetch_latest_bar failed for {sym}: {e}")
        raise

def upsert_bar(conn, sym, bar):
    """Upserts a single bar for a given symbol."""
    if not bar:
        return 0
    try:
        ts = normalize_alpaca_timestamp(bar["t"])
        session = get_market_session(ts)
        row = (sym, ts, bar["o"], bar["h"], bar["l"], bar["c"], bar["v"], session)
    except (TypeError, ValueError) as e:
        logger.warning(f"Skipping malformed bar for {sym} at ts {bar.get('t')}: {e}")
        return 0

    try:
        with conn.cursor() as cur:
            execute_values(cur, """
                INSERT INTO public.market_data_1m (symbol, ts, open, high, low, close, volume, session)
                VALUES %s
                ON CONFLICT (ts, symbol) DO UPDATE
                SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, volume=EXCLUDED.volume, session=EXCLUDED.session;
            """, [row])
        conn.commit()
        return 1
    except psycopg2.Error as e:
        logger.error(f"Database error during upsert for {sym}: {e}")
        conn.rollback()
        return 0

def main():
    """Main function: fetch latest bar for each symbol and upsert."""
    logger.info("Starting live 1-minute ingest for symbols: %s", ", ".join(SYMBOLS))
    total_upserted = 0
    try:
        with psycopg2.connect(DB_URL) as conn:
            for sym in SYMBOLS:
                latest_bar = fetch_latest_bar(sym)
                if latest_bar:
                    upserted_count = upsert_bar(conn, sym, latest_bar)
                    if upserted_count > 0:
                        logger.info(f"{sym}: upserted 1 bar")
                        total_upserted += 1
                else:
                    logger.info(f"{sym}: no new bar found")
    except psycopg2.Error as e:
        logger.critical(f"Database connection failed: {e}")
    except Exception as e:
        logger.critical(f"An unexpected error occurred: {e}")
    finally:
        logger.info(f"Live 1-minute ingest finished. Total bars upserted: {total_upserted}")

if __name__ == "__main__":
    main()