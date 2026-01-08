import sys
import os
import datetime as dt
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional, TypeVar

import requests

from backend.messaging.publisher import PubSubPublisher
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.providers import normalize_alpaca_timestamp
from backend.utils.session import get_market_session

T = TypeVar("T")

# --- Standard Header ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_symbols_raw = os.getenv("ALPACA_SYMBOLS", "SPY,IWM,QQQ")
SYMS = [s.strip() for s in _symbols_raw.split(",") if s.strip()]
FEED = os.getenv("ALPACA_FEED", "iex")
TARGET_TABLE = "public.market_data_1m"
# --- End Standard Header ---

def _env_bool(name: str, *, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "t", "yes", "y", "on")


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


def fetch_bars(*, sym: str, base: str, headers: dict[str, str], feed: str, limit: int = 100):
    """Fetches the last N bars for a symbol."""
    url = f"{base}/{sym}/bars"
    params = {"timeframe": "1Min", "limit": limit, "feed": feed, "adjustment": "all"}

    def _do():
        r = requests.get(url, headers=headers, params=params, timeout=30)
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

def _synthetic_bar_payload(*, symbol: str, ts: datetime, px: float, seq: int) -> dict[str, Any]:
    # Payload schema mirrors `market_data_1m` row shape + timeframe.
    # NOTE: `ts` is ISO-8601 string (UTC).
    o = round(px, 2)
    h = round(px + 0.10, 2)
    l = round(px - 0.10, 2)
    c = round(px + 0.02, 2)
    return {
        "symbol": symbol,
        "timeframe": "1m",
        "ts": ts.astimezone(timezone.utc).isoformat(),
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": int(1000 + (seq % 500)),
        "source": "synthetic",
    }


def _run_synthetic_mode() -> None:
    if not SYMS:
        logger.error("ALPACA_SYMBOLS resolved to an empty list; nothing to emit.")
        sys.exit(1)

    project_id = (os.getenv("PUBSUB_PROJECT_ID") or "").strip()
    if not project_id:
        raise RuntimeError("Missing required env var for SYNTHETIC_MODE: PUBSUB_PROJECT_ID")

    # Per task requirement: publish to market-bars-1m.
    topic_id = (os.getenv("MARKET_BARS_TOPIC_ID") or "market-bars-1m").strip() or "market-bars-1m"

    agent_name = (os.getenv("AGENT_NAME") or "vm-bars-ingest").strip()
    event_type = (os.getenv("MARKET_BARS_1M_EVENT_TYPE") or "market.bars.1m").strip()
    interval_s = float(os.getenv("SYNTHETIC_BAR_INTERVAL_S") or "5")

    base_px = float(os.getenv("SYNTHETIC_BASE_PRICE") or "500.0")
    px_by_symbol: dict[str, float] = {sym: base_px + float(i) for i, sym in enumerate(SYMS)}

    logger.info(
        "Synthetic mode enabled: publishing fake 1m bars | topic_id=%s symbols=%s interval_s=%s event_type=%s",
        topic_id,
        ",".join(SYMS),
        interval_s,
        event_type,
    )

    pub = PubSubPublisher(
        project_id=project_id,
        topic_id=topic_id,
        agent_name=agent_name,
        git_sha=os.getenv("GIT_SHA") or None,
        validate_credentials=not _env_bool("PUBSUB_SKIP_CREDENTIALS_VALIDATION", default=False),
    )
    try:
        seq = 0
        while True:
            now = datetime.now(timezone.utc)
            bar_ts = now.replace(second=0, microsecond=0)
            for sym in SYMS:
                # Deterministic walk (avoid randomness for stable debugging).
                px_by_symbol[sym] = float(px_by_symbol.get(sym, base_px)) + 0.05
                payload = _synthetic_bar_payload(symbol=sym, ts=bar_ts, px=px_by_symbol[sym], seq=seq)
                pub.publish_event(event_type=event_type, payload=payload)
            seq += 1
            time.sleep(max(0.1, interval_s))
    finally:
        try:
            pub.close()
        except Exception:
            logger.exception("alpaca_bars_ingest.pubsub_publisher_close_failed")
            pass


def main():
    """Main function to fetch and upsert bars for all symbols."""
    if _env_bool("SYNTHETIC_MODE", default=False) or _env_bool("VM_INGESTION_SYNTHETIC_MODE", default=False):
        _run_synthetic_mode()
        return

    if not SYMS:
        logger.error("ALPACA_SYMBOLS resolved to an empty list; nothing to ingest.")
        sys.exit(1)

    db_url = os.getenv("DATABASE_URL")
    alpaca = load_alpaca_env(require_keys=True)
    base = alpaca.data_stocks_base_v2
    headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}

    logger.info("Starting short-window ingest...")
    logger.info("Resolved target table: %s | symbols: %s | feed: %s", TARGET_TABLE, ", ".join(SYMS), FEED)
    total_upserted = 0
    # API-only mode for Cloud Shell / local smoke tests.
    if not db_url:
        for s in SYMS:
            bars = fetch_bars(sym=s, base=base, headers=headers, feed=FEED, limit=5)
            logger.info("%s: fetched %d bars (API-only mode; DATABASE_URL not set)", s, len(bars))
        logger.info("Short-window ingest finished (API-only mode).")
        return

    try:
        with _connect_db(db_url) as conn:
            for s in SYMS:
                bars = fetch_bars(sym=s, base=base, headers=headers, feed=FEED)
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
