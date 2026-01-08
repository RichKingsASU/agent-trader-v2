import os
import sys
import subprocess
import psycopg2
import logging
from decimal import Decimal

from backend.common.logging import init_structured_logging

init_structured_logging(service="naive-strategy-driver")
logger = logging.getLogger(__name__)

# --- Configuration ---
DB_URL = os.getenv("DATABASE_URL")
if not DB_URL:
    logger.critical(
        "DATABASE_URL missing; refusing to start",
        extra={"event_type": "config.missing", "missing": ["DATABASE_URL"]},
    )
    sys.exit(1)

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
