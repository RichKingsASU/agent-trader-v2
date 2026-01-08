import os
import time
import random
import uuid
import logging
from datetime import datetime, timezone

import psycopg

from backend.common.logging import init_structured_logging

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is not set")

SYMBOL = "SPY"

init_structured_logging(service="dummy-market-data-streamer")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info(
        "dummy_stream.startup",
        extra={"event_type": "dummy_stream.startup", "symbol": SYMBOL},
    )

    base_price = 500.0  # starting reference

    with psycopg.connect(DATABASE_URL) as conn:
        while True:
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
                logger.exception(
                    "dummy_stream.error",
                    extra={"event_type": "dummy_stream.error", "error": repr(e)},
                )
                time.sleep(2.0)

            time.sleep(1.0)


if __name__ == "__main__":
    main()
