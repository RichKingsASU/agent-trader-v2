import os
import logging
import signal
import threading
import time
import random
import uuid
import logging
from datetime import datetime, timezone

import psycopg

from backend.common.logging import init_structured_logging

from backend.common.secrets import get_secret

SYMBOL = "SPY"
logger = logging.getLogger(__name__)
_SHUTDOWN_EVENT = threading.Event()

init_structured_logging(service="dummy-market-data-streamer")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info(
        "dummy_stream.startup",
        extra={"event_type": "dummy_stream.startup", "symbol": SYMBOL},
    )

    base_price = 500.0  # starting reference

    # Best-effort: allow clean SIGTERM/SIGINT shutdown (Cloud Run, ctrl-c).
    def _handle_signal(signum, _frame=None):  # type: ignore[no-untyped-def]
        _SHUTDOWN_EVENT.set()
        try:
            logger.info("dummy_market_data signal_received signum=%s", int(signum))
        except Exception:
            pass

    if threading.current_thread() is threading.main_thread():
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, _handle_signal)
            except Exception:
                pass

    db_url = get_secret("DATABASE_URL", required=True)
    with psycopg.connect(db_url) as conn:
        iteration = 0
        while not _SHUTDOWN_EVENT.is_set():
            iteration += 1
            print(f"[streamer] loop_iteration={iteration}")
            try:
                iteration_id = uuid.uuid4().hex
                # random walk around base_price
                base_price_delta = random.uniform(-0.5, 0.5)
                base_price_local = base_price + base_price_delta
                base_price = base_price_local

                high = base_price_local + random.uniform(0.1, 1.0)
                low = base_price_local - random.uniform(0.1, 1.0)
                open_ = base_price_local + random.uniform(-0.5, 0.5)
                close = base_price_local + random.uniform(-0.5, 0.5)
                volume = random.randint(10_000, 100_000)
                ts = datetime.now(timezone.utc)

                insert_sql = """
                    INSERT INTO public.market_data_1m (
                        symbol, ts, open, high, low, close, volume
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING ts, symbol, open, high, low, close, volume;
                """

                with conn.cursor() as cur:
                    cur.execute(
                        insert_sql,
                        (SYMBOL, ts, open_, high, low, close, volume),
                    )
                    row = cur.fetchone()
                    conn.commit()

                logger.info(
                    "dummy_stream.inserted",
                    extra={
                        "event_type": "dummy_stream.inserted",
                        "iteration_id": iteration_id,
                        "ts": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
                        "symbol": row[1],
                        "open": float(row[2]),
                        "high": float(row[3]),
                        "low": float(row[4]),
                        "close": float(row[5]),
                        "volume": int(row[6]),
                    },
                )
            except Exception as e:
                print(f"[streamer] ERROR: {e!r}")
                _SHUTDOWN_EVENT.wait(timeout=2.0)

            _SHUTDOWN_EVENT.wait(timeout=1.0)


if __name__ == "__main__":
    main()
