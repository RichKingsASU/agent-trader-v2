import random
from datetime import datetime, timezone
import logging

import psycopg

from backend.common.logging import init_structured_logging
from backend.common.secrets import get_secret


def main() -> None:
    init_structured_logging(service="test-insert-market-candle")
    logger = logging.getLogger(__name__)

    symbol = "SPY"

    # Simple random candle around 500
    base = 500.0 + random.uniform(-5, 5)
    high = base + random.uniform(0.1, 1.0)
    low = base - random.uniform(0.1, 1.0)
    open_ = base + random.uniform(-0.5, 0.5)
    close = base + random.uniform(-0.5, 0.5)
    volume = random.randint(1_000, 10_000)
    ts = datetime.now(timezone.utc)

    insert_sql = """
    INSERT INTO public.market_data_1m (
        symbol, ts, open, high, low, close, volume
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING ts, symbol, open, high, low, close, volume;
    """

    db_url = get_secret("DATABASE_URL", required=True)
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(insert_sql, (symbol, ts, open_, high, low, close, volume))
            row = cur.fetchone()

    logger.info(
        "inserted_market_candle",
        extra={
            "event_type": "db.inserted_market_candle",
            "symbol": symbol,
            "ts": ts.isoformat(),
            "row": row,
        },
    )


if __name__ == "__main__":
    main()
