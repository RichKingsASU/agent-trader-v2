import os
import sys
import subprocess
import psycopg2
import logging
from decimal import Decimal
from datetime import timedelta

from backend.common.logging import init_structured_logging
from backend.common.freshness import check_freshness, stale_after_for_bar_interval
from backend.common.secrets import get_database_url

init_structured_logging(service="naive-strategy-driver")
logger = logging.getLogger(__name__)

# --- Configuration ---
DB_URL = get_database_url(required=True)

def get_last_n_bars(symbol: str, n: int, session: str = 'REGULAR'):
    """Fetches the last N bars for a symbol from the database."""
    logger.info(
        "Fetching bars",
        extra={"event_type": "bars.fetch", "symbol": symbol, "n": n, "session": session},
    )
    try:
        with psycopg2.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ts, open, high, low, close, volume
                    FROM public.market_data_1m
                    WHERE symbol = %s AND session = %s
                    ORDER BY ts DESC
                    LIMIT %s
                    """,
                    (symbol, session, n)
                )
                return cur.fetchall()
    except psycopg2.Error as e:
        logger.exception(
            "Database error fetching bars",
            extra={"event_type": "bars.fetch_failed", "symbol": symbol, "session": session, "error": str(e)},
        )
        return []

def run_strategy(symbol: str, execute: bool = False):
    """Runs a naive strategy: if the last close is higher than the previous, signal a buy."""
    bars = get_last_n_bars(symbol, 2)
    if len(bars) < 2:
        logger.warning(
            "Not enough data to run strategy",
            extra={"event_type": "strategy.no_data", "symbol": symbol, "bars": len(bars)},
        )
        return

    latest_bar = bars[0]
    previous_bar = bars[1]

    # Fail-closed: refuse to evaluate if the latest bar timestamp is stale
    # or too far in the future (clock skew / bad upstream data).
    # Default bar interval is 60s; stale after 2x interval. Override via env.
    try:
        latest_ts = latest_bar[0]
        max_future_skew_s = float(os.getenv("STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS") or "5")
        try:
            max_future_skew_s = max(0.0, float(max_future_skew_s))
        except Exception:
            max_future_skew_s = 5.0
        # Note: check_freshness treats negative age as "fresh", so enforce future skew explicitly.
        try:
            from datetime import datetime, timezone

            ts_utc = latest_ts if getattr(latest_ts, "tzinfo", None) is not None else latest_ts.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            if (ts_utc.astimezone(timezone.utc) - now_utc).total_seconds() > max_future_skew_s:
                logger.warning(
                    "FUTURE_TIMESTAMP refusing_to_evaluate",
                    extra={
                        "event_type": "strategy.future_timestamp",
                        "symbol": symbol,
                        "latest_ts_utc": ts_utc.astimezone(timezone.utc).isoformat(),
                        "now_utc": now_utc.isoformat(),
                        "max_future_skew_seconds": max_future_skew_s,
                    },
                )
                return
        except Exception:
            # If we can't validate future-skew, fail-closed below in the generic exception handler.
            raise

        bar_interval_s = int(os.getenv("MARKETDATA_BAR_INTERVAL_SECONDS") or "60")
        bar_interval_s = max(1, bar_interval_s)
        stale_after = stale_after_for_bar_interval(bar_interval=timedelta(seconds=bar_interval_s), multiplier=2.0)
        override = (os.getenv("MARKETDATA_STALE_AFTER_SECONDS") or "").strip()
        if override:
            stale_after = timedelta(seconds=max(0, int(override)))

        freshness = check_freshness(latest_ts=latest_ts, stale_after=stale_after, source="bars:public.market_data_1m")
        if not freshness.ok:
            logger.warning(
                "STALE_DATA refusing_to_evaluate",
                extra={
                    "event_type": "strategy.stale_data",
                    "symbol": symbol,
                    "reason_code": freshness.reason_code,
                    "latest_ts_utc": (freshness.latest_ts_utc.isoformat() if freshness.latest_ts_utc else None),
                    "age_seconds": (float(freshness.age.total_seconds()) if freshness.age is not None else None),
                    "threshold_seconds": float(freshness.stale_after.total_seconds()),
                    "source": freshness.details.get("source"),
                },
            )
            return
    except Exception as e:
        logger.warning(
            "STALE_DATA refusing_to_evaluate due_to_timestamp_error",
            extra={"event_type": "strategy.stale_data_error", "symbol": symbol, "error": str(e)},
        )
        return

    latest_close = Decimal(latest_bar[4])
    previous_close = Decimal(previous_bar[4])

    logger.info(
        "Computed closes",
        extra={
            "event_type": "strategy.closes",
            "symbol": symbol,
            "latest_close": str(latest_close),
            "previous_close": str(previous_close),
        },
    )

    if latest_close > previous_close:
        logger.info("Strategy signal: BUY", extra={"event_type": "strategy.signal", "symbol": symbol, "signal": "BUY"})
        if execute:
            logger.warning(
                "Executing trade (paper)",
                extra={"event_type": "strategy.execute", "symbol": symbol, "side": "buy", "qty": 1},
            )
            try:
                subprocess.run(
                    ["python", "backend/streams/manual_paper_trade.py", symbol, "buy", "1"],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                logger.exception(
                    "Error executing trade",
                    extra={"event_type": "strategy.execute_failed", "symbol": symbol, "error": str(e)},
                )
        else:
            logger.info(
                "Dry run: no trade executed",
                extra={"event_type": "strategy.dry_run", "symbol": symbol},
            )
    else:
        logger.info(
            "Strategy signal: HOLD",
            extra={"event_type": "strategy.signal", "symbol": symbol, "signal": "HOLD"},
        )

def main():
    """Main function to run the strategy driver."""
    symbol = "SPY"  # Default to SPY
    execute = "--execute" in sys.argv

    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        symbol = sys.argv[1].upper()

    logger.info("Running naive strategy", extra={"event_type": "strategy.run_start", "symbol": symbol, "execute": execute})
    run_strategy(symbol, execute)

if __name__ == "__main__":
    main()
