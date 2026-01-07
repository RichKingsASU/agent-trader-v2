
import datetime as dt
import logging
import os

import psycopg2
import requests
from psycopg2.extras import execute_values
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.common.agent_boot import configure_startup_logging
from backend.streams.alpaca_env import load_alpaca_env
from backend.common.timeutils import parse_alpaca_timestamp

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@retry(wait=wait_exponential(multiplier=1, min=4, max=10), stop=stop_after_attempt(5))
def fetch_bars(*, base: str, headers: dict[str, str], sym: str, start_iso: str, end_iso: str, feed: str, limit: int = 10000):
    try:
        r = requests.get(
            f"{base.rstrip('/')}/{sym}/bars",
            headers=headers,
            params={
                "timeframe": "1Min",
                "start": start_iso,
                "end": end_iso,
                "limit": limit,
                "feed": feed,
                "adjustment": "all",
            },
            timeout=30,
        )
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
    configure_startup_logging(
        agent_name="alpaca-bars-backfill",
        intent="Backfill historical 1-minute bars from Alpaca into Postgres.",
    )
    logger.info("Alpaca backfill script started.")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.critical("Missing required env var: DATABASE_URL")
        return

    alpaca = load_alpaca_env(require_keys=True)
    headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}
    base = alpaca.data_stocks_base_v2

    feed = os.getenv("ALPACA_FEED", "iex")
    syms = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM").split(",") if s.strip()]
    days = int(os.getenv("ALPACA_BACKFILL_DAYS", "5"))

    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=days)
    start_iso = start.isoformat(timespec="seconds").replace("+00:00", "Z")
    end_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")

    try:
        with psycopg2.connect(db_url, sslmode="require") as conn:
            for s in syms:
                try:
                    bars = fetch_bars(
                        base=base,
                        headers=headers,
                        sym=s,
                        start_iso=start_iso,
                        end_iso=end_iso,
                        feed=feed,
                    )
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
