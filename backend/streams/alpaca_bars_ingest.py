import sys
import os
import datetime as dt
import logging
import time
from typing import Any, Callable, Optional, TypeVar

import requests
T = TypeVar("T")

from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session

# --- Standard Header ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_URL = os.getenv("DATABASE_URL")
alpaca = load_alpaca_env()
KEY = alpaca.key_id
SEC = alpaca.secret_key
_symbols_raw = os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ")
SYMS = [s.strip() for s in _symbols_raw.split(",") if s.strip()]
FEED = os.getenv("ALPACA_FEED", "iex")
BASE = alpaca.data_stocks_base_v2
HDRS = {"APCA-API-KEY-ID": KEY, "APCA-API-SECRET-KEY": SEC}
TARGET_TABLE = "public.market_data_1m"
# --- End Standard Header ---


def _retry(fn: Callable[[], T], *, attempts: int = 5, base_sleep_s: float = 1.0) -> T:
    last_err: Optional[BaseException] = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            sleep_s = min(base_sleep_s * (2**i), 10.0)
            time.sleep(sleep_s)
    assert last_err is not None
    raise last_err


def fetch_bars(sym, limit=100):
    """Fetches the last N bars for a symbol."""
    url = f"{BASE}/{sym}/bars"
    params = {"timeframe": "1Min", "limit": limit, "feed": FEED, "adjustment": "all"}

    def _do():
        r = requests.get(url, headers=HDRS, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("bars", [])

    try:
        return _retry(_do)
    except requests.exceptions.RequestException as e:
        logger.error(f"Error fetching bars for {sym}: {e}")
        raise


def _connect_db(db_url: str):
    """
    Lazily import a DB driver only when DATABASE_URL is set.
    Prefer psycopg2 for compatibility with existing schema scripts.
    """
    try:
        import psycopg2  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "DATABASE_URL is set but psycopg2 is not installed in this environment. "
            "Install it (e.g. pip install psycopg2-binary) or unset DATABASE_URL for API-only mode."
        ) from e
    return psycopg2.connect(db_url)

def upsert_bars(conn, sym, bars) -> int:
    """Upserts a list of bars for a given symbol into the database."""
    if not bars:
        return 0

    # Import only when we actually upsert.
    from psycopg2.extras import execute_values  # type: ignore

    rows = []
    for b in bars:
        try:
            ts = normalize_alpaca_timestamp(b["t"])
            session = get_market_session(ts)
            o, h, l, c, v = b.get("o"), b.get("h"), b.get("l"), b.get("c"), b.get("v")
            # public.market_data_1m has NOT NULL columns; skip incomplete bars.
            if o is None or h is None or l is None or c is None or v is None:
                logger.warning(f"Skipping incomplete bar for {sym} at ts {b.get('t')}")
                continue
            rows.append(
                (
                    sym,
                    ts,
                    o,
                    h,
                    l,
                    c,
                    int(v),
                    session,
                )
            )
        except (TypeError, ValueError) as e:
            logger.warning(f"Skipping malformed bar for {sym} at ts {b.get('t')}: {e}")
            continue
    
    if not rows:
        return 0

    try:
        with conn.cursor() as cur:
            execute_values(cur, f"""
                INSERT INTO {TARGET_TABLE} (symbol, ts, open, high, low, close, volume, session)
                VALUES %s
                ON CONFLICT (ts, symbol) DO UPDATE
                  SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
                      close=EXCLUDED.close, volume=EXCLUDED.volume, session=EXCLUDED.session;
            """, rows)
        conn.commit()
        return len(rows)
    except Exception as e:
        logger.error(f"Database error during upsert for {sym}: {e}")
        conn.rollback()
        return 0

def main():
    """Main function to fetch and upsert bars for all symbols."""
    if not SYMS:
        logger.error("ALPACA_SYMBOLS resolved to an empty list; nothing to ingest.")
        sys.exit(1)

    logger.info("Starting short-window ingest...")
    logger.info("Resolved target table: %s | symbols: %s | feed: %s", TARGET_TABLE, ", ".join(SYMS), FEED)
    total_upserted = 0
    # API-only mode for Cloud Shell / local smoke tests.
    if not DB_URL:
        for s in SYMS:
            bars = fetch_bars(s, limit=5)
            logger.info("%s: fetched %d bars (API-only mode; DATABASE_URL not set)", s, len(bars))
        logger.info("Short-window ingest finished (API-only mode).")
        return

    try:
        with _connect_db(DB_URL) as conn:
            for s in SYMS:
                bars = fetch_bars(s)
                upserted_count = upsert_bars(conn, s, bars)
                logger.info(f"{s}: upserted {upserted_count} bars")
                total_upserted += upserted_count
    except Exception as e:
        logger.critical(f"Bars ingest failed: {e}")
        raise
    finally:
        logger.info(f"Short-window ingest finished. Total bars upserted: {total_upserted}")

    # Fail fast if nothing was written (enables retries/alerts)
    if total_upserted == 0:
        logger.error("No bars upserted. Failing execution to trigger retry/alerting.")
        sys.exit(1)

if __name__ == "__main__":
    main()
