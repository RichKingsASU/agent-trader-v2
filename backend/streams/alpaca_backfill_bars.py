from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import datetime as dt
import json
import logging
import os

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.common.agent_boot import configure_startup_logging
from backend.common.logging import init_structured_logging
from backend.common.preflight import preflight_or_exit
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.streams.alpaca_env import load_alpaca_env
from backend.time.nyse_time import NYSE_TZ, is_trading_day, market_open_dt
from backend.time.providers import normalize_alpaca_timestamp

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


def _connect_db(db_url: str):
    """
    Lazily import psycopg2 only when DATABASE_URL is set.
    """
    try:
        import psycopg2  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "DATABASE_URL is set but psycopg2 is not installed. "
            "Install it (e.g. pip install psycopg2-binary) to enable backfill writes."
        ) from e
    return psycopg2.connect(db_url, sslmode="require")


def _compute_start_iso_for_trading_days(*, trading_days: int, now_utc: dt.datetime) -> str:
    """
    Compute an ISO Z timestamp aligned to NYSE open for (N trading days ago).

    If exchange calendars are unavailable, this falls back to weekday-only logic
    (still good enough for "seed last ~30 trading days" tonight).
    """
    n = max(1, int(trading_days))
    now_ny = now_utc.astimezone(NYSE_TZ)
    d = now_ny.date()
    # Walk backward counting only trading days.
    count = 0
    while True:
        if is_trading_day(d):
            count += 1
            if count >= n:
                break
        d = d - dt.timedelta(days=1)
    start_ny = market_open_dt(d)
    start_utc = start_ny.astimezone(dt.timezone.utc)
    return start_utc.isoformat(timespec="seconds").replace("+00:00", "Z")

def upsert_bars(conn, sym, bars):
    if not bars: return 0
    from psycopg2.extras import execute_values  # type: ignore  # noqa: WPS433

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
    except Exception as e:
        logger.error(f"Database error during upsert for {sym}: {e}")
        conn.rollback()
        return 0

def main():
    configure_startup_logging(
        agent_name="alpaca-bars-backfill",
        intent="Backfill historical 1-minute bars from Alpaca into Postgres.",
    )
    # Fail fast with an explicit preflight report.
    preflight_or_exit(extra_required_env=["DATABASE_URL"])
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

    db_url = os.getenv("DATABASE_URL")  # guaranteed by preflight_or_exit()

    alpaca = load_alpaca_env(require_keys=True)
    headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}
    base = alpaca.data_stocks_base_v2

    feed = os.getenv("ALPACA_FEED", "iex")
    syms = [s.strip().upper() for s in os.getenv("ALPACA_SYMBOLS", "SPY,IWM").split(",") if s.strip()]
    trading_days_env = os.getenv("ALPACA_BACKFILL_TRADING_DAYS")
    days_env = os.getenv("ALPACA_BACKFILL_DAYS")
    now = dt.datetime.now(dt.timezone.utc)
    if trading_days_env and str(trading_days_env).strip():
        start_iso = _compute_start_iso_for_trading_days(trading_days=int(trading_days_env), now_utc=now)
    else:
        # Back-compat: calendar days window.
        days = int(days_env or "5")
        start = now - dt.timedelta(days=days)
        start_iso = start.isoformat(timespec="seconds").replace("+00:00", "Z")
    end_iso = now.isoformat(timespec="seconds").replace("+00:00", "Z")

    try:
        with _connect_db(db_url) as conn:
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
    except Exception as e:
        logger.critical(f"Backfill failed: {e}")
        raise
    finally:
        logger.info("Alpaca backfill script finished.")

if __name__ == "__main__":
    main()
