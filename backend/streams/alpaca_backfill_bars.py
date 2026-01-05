
import os, requests, psycopg2, datetime as dt
import logging
from psycopg2.extras import execute_values
from tenacity import retry, wait_exponential, stop_after_attempt, Retrying

from backend.streams.alpaca_env import load_alpaca_env
from backend.common.timeutils import parse_alpaca_timestamp

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    raise RuntimeError("Missing required env var: DATABASE_URL")
alpaca = load_alpaca_env()
KEY = alpaca.key_id
SEC = alpaca.secret_key
FEED = os.getenv("ALPACA_FEED", "iex")
SYMS = os.getenv("ALPACA_SYMBOLS", "SPY,IWM").split(",")
DAYS = int(os.getenv("ALPACA_BACKFILL_DAYS", "5"))

HDRS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}
BASE = alpaca.data_stocks_base_v2

@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5))
def fetch_bars(sym, start_iso, end_iso, limit=10000):
    try:
        r = requests.get(f"{BASE}/{sym}/bars",
            headers=HDRS,
            params={"timeframe":"1Min","start":start_iso,"end":end_iso,"limit":limit,"feed":FEED,"adjustment":"all"},
            timeout=30)
        r.raise_for_status()
        return r.json().get("bars", [])
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching bars for {sym}: {e}")
        raise

def upsert_bars(conn, sym, bars):
    if not bars: return 0
    rows = []
    for b in bars:
        ts = parse_alpaca_timestamp(b["t"])
        rows.append((sym, ts, b["o"], b["h"], b["l"], b["c"], b["v"]))
    try:
        with conn.cursor() as cur:
            execute_values(cur, """
              INSERT INTO public.market_data_1m (symbol, ts, open, high, low, close, volume)
              VALUES %s
              ON CONFLICT (ts, symbol) DO UPDATE
                SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                    close=EXCLUDED.close, volume=EXCLUDED.volume;""", rows)
        conn.commit()
        return len(rows)
    except psycopg2.Error as e:
        logger.error(f"Database error during upsert for {sym}: {e}")
        conn.rollback()
        return 0

def main():
    logger.info("Alpaca backfill script started.")
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=DAYS)
    start_iso = start.isoformat(timespec="seconds").replace("+00:00","Z")
    end_iso   = now.isoformat(timespec="seconds").replace("+00:00","Z")

    try:
        with psycopg2.connect(DB_URL, sslmode="require") as conn:
            for s in SYMS:
                try:
                    bars = fetch_bars(s, start_iso, end_iso)
                    n = upsert_bars(conn, s, bars)
                    logger.info(f"{s}: upserted {n} bars from {start_iso} to {end_iso}")
                except Exception as e:
                    logger.error(f"Failed to process symbol {s}: {e}")
    except psycopg2.Error as e:
        logger.critical(f"Database connection failed: {e}")
        return # Exit if DB connection fails
    except Exception as e:
        logger.critical(f"An unexpected error occurred: {e}")
    finally:
        logger.info("Alpaca backfill script finished.")

if __name__ == "__main__":
    main()
