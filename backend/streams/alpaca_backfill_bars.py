from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import datetime as dt
import json
import logging
import os

import psycopg2
import requests
from psycopg2.extras import execute_values
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.common.alpaca_env import configure_alpaca_env
from backend.common.agent_boot import configure_startup_logging
from backend.common.logging import init_structured_logging
from backend.common.secrets import get_database_url
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
import os

init_structured_logging(service="alpaca-bars-backfill")
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
        ts = normalize_alpaca_timestamp(b["t"])
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
    try:
        fp = get_build_fingerprint()
        logger.info(
            "build_fingerprint",
            extra={
                "event_type": "build_fingerprint",
                "intent_type": "build_fingerprint",
                "service": "alpaca-bars-backfill",
                **fp,
            },
        )
    except Exception:
        pass
    logger.info("Alpaca backfill script started.")

    # Fail-fast: secrets must come from Secret Manager (no shell exports).
    _ = configure_alpaca_env(required=True)
    db_url = get_database_url(required=True)

alpaca = load_alpaca_env(require_keys=True)

# Task 1: Resolve ALPACA_FEED naming conflict. Fetch explicit feeds.
equities_feed = get_alpaca_equities_feed()
options_feed = get_alpaca_options_feed() # This will be None if only equities feed is found.

# Determine the feed to use:
# Priority: 1. equities_feed, 2. options_feed (if only one found, treat as equities), 3. env var, 4. default 'iex'.
feed = equities_feed
if not feed and options_feed:
    feed = options_feed # Treat options feed as equities if it's the only one found.

# Fallback to env var or default if feed is still empty.
feed = feed or os.getenv("ALPACA_FEED", "iex") # Fallback to env var or default 'iex'
feed = str(feed).strip().lower() or "iex" # Ensure it's lowercased and not empty

syms = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM").split(",") if s.strip()]
days = int(os.getenv("ALPACA_BACKFILL_DAYS", "5"))