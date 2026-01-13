from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import datetime as dt
import logging
import os
from dataclasses import dataclass
from typing import Iterable

import psycopg
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from backend.streams.alpaca_env import load_alpaca_env
from backend.time.nyse_time import NYSE_TZ, UTC, is_trading_day, market_close_dt, market_open_dt, to_nyse, utc_now
from backend.time.providers import normalize_alpaca_timestamp

logger = logging.getLogger(__name__)


def _env_bool(name: str, *, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _env_list(name: str, *, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [p.strip().upper() for p in raw.split(",") if p.strip()]


def _to_iso_z(ts_utc: dt.datetime) -> str:
    ts_utc = ts_utc.astimezone(UTC)
    return ts_utc.isoformat(timespec="seconds").replace("+00:00", "Z")


def _last_n_trading_days(*, n: int) -> list[dt.date]:
    """
    Return the most recent N NYSE trading dates (NY local), ending at the most recent
    fully-known session date (i.e., up to the last close).
    """
    if n <= 0:
        raise ValueError("n must be > 0")

    # Use the most recent close as the anchor to avoid partial "today" sessions.
    now_utc = utc_now()
    anchor_ny = to_nyse(now_utc)
    d = anchor_ny.date()

    # Walk back to the most recent trading day (handles weekends/holidays via calendar if enabled).
    while not is_trading_day(d):
        d = d - dt.timedelta(days=1)

    out: list[dt.date] = []
    while len(out) < n:
        if is_trading_day(d):
            out.append(d)
        d = d - dt.timedelta(days=1)
    out.reverse()
    return out


@dataclass(frozen=True, slots=True)
class TimeframeSpec:
    text: str  # "1m" | "5m"
    alpaca: str  # "1Min" | "5Min"
    step_minutes: int


_TIMEFRAMES: dict[str, TimeframeSpec] = {
    "1m": TimeframeSpec(text="1m", alpaca="1Min", step_minutes=1),
    "5m": TimeframeSpec(text="5m", alpaca="5Min", step_minutes=5),
}


def _expected_bars_per_session(tf: TimeframeSpec) -> int:
    # Regular session: 09:30–16:00 NY time => 390 minutes.
    minutes = 390
    if minutes % tf.step_minutes != 0:
        raise AssertionError("unexpected step that does not evenly divide the RTH session")
    return minutes // tf.step_minutes


def _is_aligned_to_nyse_session(ts_start_utc: dt.datetime, *, tf: TimeframeSpec, session_date_ny: dt.date) -> bool:
    """
    Ensure the bar start is aligned to NYSE wall-clock boundaries for the given session day.
    This is the "timezone normalization" check: bars must be anchored to America/New_York
    boundaries (09:30 open) and step minutes.
    """
    ts_ny = ts_start_utc.astimezone(NYSE_TZ)
    if ts_ny.date() != session_date_ny:
        return False
    if ts_ny.second != 0 or ts_ny.microsecond != 0:
        return False

    open_ny = market_open_dt(session_date_ny)
    close_ny = market_close_dt(session_date_ny)
    if not (open_ny <= ts_ny < close_ny):
        return False

    # Step alignment relative to 09:30, not relative to :00.
    delta_min = int((ts_ny - open_ny).total_seconds() // 60)
    return (delta_min % tf.step_minutes) == 0


@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(5))
def _fetch_alpaca_bars(
    *,
    base: str,
    headers: dict[str, str],
    sym: str,
    timeframe: str,
    start_iso: str,
    end_iso: str,
    feed: str,
    limit: int = 10000,
) -> list[dict]:
    url = f"{base.rstrip('/')}/{sym}/bars"
    r = requests.get(
        url,
        headers=headers,
        params={
            "timeframe": timeframe,
            "start": start_iso,
            "end": end_iso,
            "limit": limit,
            "feed": feed,
            "adjustment": "all",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("bars", []) or []


def _existing_ts_starts(
    conn: psycopg.Connection,
    *,
    symbol: str,
    timeframe: str,
    start_utc: dt.datetime,
    end_utc: dt.datetime,
) -> set[dt.datetime]:
    sql = """
    SELECT ts_start
    FROM public.market_candles
    WHERE symbol = %s
      AND timeframe = %s
      AND ts_start >= %s
      AND ts_start < %s
    """
    out: set[dt.datetime] = set()
    with conn.cursor() as cur:
        cur.execute(sql, (symbol, timeframe, start_utc, end_utc))
        for (ts_start,) in cur.fetchall():
            # psycopg returns tz-aware datetimes for timestamptz columns.
            out.add(ts_start.astimezone(UTC))
    return out


def _upsert_missing_bars(
    conn: psycopg.Connection,
    *,
    symbol: str,
    tf: TimeframeSpec,
    session_date_ny: dt.date,
    session_open_utc: dt.datetime,
    session_close_utc: dt.datetime,
    feed: str,
    alpaca_base: str,
    alpaca_headers: dict[str, str],
    dry_run: bool,
) -> int:
    expected = _expected_bars_per_session(tf)
    existing = _existing_ts_starts(
        conn,
        symbol=symbol,
        timeframe=tf.text,
        start_utc=session_open_utc,
        end_utc=session_close_utc,
    )
    if len(existing) >= expected:
        return 0

    start_iso = _to_iso_z(session_open_utc)
    # Add one step to end to avoid edge ambiguity on inclusivity for the final bar.
    end_iso = _to_iso_z(session_close_utc + dt.timedelta(minutes=tf.step_minutes))

    bars = _fetch_alpaca_bars(
        base=alpaca_base,
        headers=alpaca_headers,
        sym=symbol,
        timeframe=tf.alpaca,
        start_iso=start_iso,
        end_iso=end_iso,
        feed=feed,
    )

    rows: list[tuple] = []
    misaligned = 0
    for b in bars:
        ts_start = normalize_alpaca_timestamp(b.get("t")).astimezone(UTC)
        if not (session_open_utc <= ts_start < session_close_utc):
            continue
        if ts_start in existing:
            continue
        if not _is_aligned_to_nyse_session(ts_start, tf=tf, session_date_ny=session_date_ny):
            misaligned += 1
            continue

        ts_end = ts_start + dt.timedelta(minutes=tf.step_minutes)
        rows.append(
            (
                symbol,
                tf.text,
                ts_start,
                ts_end,
                float(b.get("o")),
                float(b.get("h")),
                float(b.get("l")),
                float(b.get("c")),
                int(b.get("v") or 0),
                None if b.get("vw") is None else float(b.get("vw")),
                int(b.get("n") or 0),
                True,
            )
        )

    if misaligned:
        logger.warning(
            "timezone_alignment: dropped %d misaligned bars | symbol=%s tf=%s session_date=%s",
            misaligned,
            symbol,
            tf.text,
            str(session_date_ny),
        )

    if not rows:
        return 0

    if dry_run:
        logger.info(
            "dry_run: would insert %d bars | symbol=%s tf=%s session_date=%s",
            len(rows),
            symbol,
            tf.text,
            str(session_date_ny),
        )
        return len(rows)

    insert_sql = """
    INSERT INTO public.market_candles
      (symbol, timeframe, ts_start, ts_end, open, high, low, close, volume, vwap, trade_count, is_final)
    VALUES
      (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT (symbol, timeframe, ts_start) DO NOTHING
    """

    with conn.cursor() as cur:
        cur.executemany(insert_sql, rows)
    conn.commit()
    return len(rows)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("Missing required env var: DATABASE_URL")

    symbols = _env_list("ALPACA_SYMBOLS", default="SPY,QQQ,IWM,AAPL,TSLA")
    tf_texts = _env_list("CANDLE_TIMEFRAMES", default="1m,5m")
    trading_days = int(os.getenv("BACKFILL_TRADING_DAYS", "30"))
    feed = os.getenv("ALPACA_FEED", "iex")
    dry_run = _env_bool("DRY_RUN", default=False)

    tfs: list[TimeframeSpec] = []
    for t in tf_texts:
        spec = _TIMEFRAMES.get(t.lower())
        if spec is None:
            raise RuntimeError(f"Unsupported timeframe {t!r}. Supported: {sorted(_TIMEFRAMES.keys())}")
        tfs.append(spec)

    alpaca = load_alpaca_env(require_keys=True)
    alpaca_base = alpaca.data_stocks_base_v2
    alpaca_headers = {"APCA-API-KEY-ID": alpaca.key_id, "APCA-API-SECRET-KEY": alpaca.secret_key}

    session_days = _last_n_trading_days(n=trading_days)
    logger.info(
        "starting_underlying_intraday_backfill symbols=%s timeframes=%s trading_days=%d dry_run=%s",
        ",".join(symbols),
        ",".join([tf.text for tf in tfs]),
        trading_days,
        str(dry_run).lower(),
    )

    total_inserted = 0
    with psycopg.connect(database_url) as conn:
        for d_ny in session_days:
            open_ny = market_open_dt(d_ny)
            close_ny = market_close_dt(d_ny)
            open_utc = open_ny.astimezone(UTC)
            close_utc = close_ny.astimezone(UTC)

            for sym in symbols:
                for tf in tfs:
                    try:
                        inserted = _upsert_missing_bars(
                            conn,
                            symbol=sym,
                            tf=tf,
                            session_date_ny=d_ny,
                            session_open_utc=open_utc,
                            session_close_utc=close_utc,
                            feed=feed,
                            alpaca_base=alpaca_base,
                            alpaca_headers=alpaca_headers,
                            dry_run=dry_run,
                        )
                        if inserted:
                            logger.info(
                                "backfilled symbol=%s tf=%s session_date=%s inserted=%d",
                                sym,
                                tf.text,
                                str(d_ny),
                                inserted,
                            )
                        total_inserted += inserted
                    except Exception:
                        logger.exception("backfill_failed symbol=%s tf=%s session_date=%s", sym, tf.text, str(d_ny))

    logger.info("underlying_intraday_backfill_done inserted_total=%d", total_inserted)


if __name__ == "__main__":
    main()

