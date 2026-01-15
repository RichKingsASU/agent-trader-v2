import os
import random
from datetime import datetime, timezone
import logging

import psycopg

from backend.common.logging import init_structured_logging

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is not set")

init_structured_logging(service="test-insert-market-candle")
logger = logging.getLogger(__name__)

TABLE = "public.market_data_1m"

symbol_raw = "SPY"
symbol = (symbol_raw or "").strip().upper()
if not symbol:
    raise RuntimeError("symbol resolved to empty")

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

with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {TABLE};")
        before_count = int(cur.fetchone()[0])
        cur.execute(f"SELECT MAX(ts) FROM {TABLE};")
        before_max_ts = cur.fetchone()[0]

        cur.execute(insert_sql, (symbol, ts, open_, high, low, close, volume))
        row = cur.fetchone()
        conn.commit()

        cur.execute(f"SELECT COUNT(*) FROM {TABLE};")
        after_count = int(cur.fetchone()[0])
        cur.execute(f"SELECT MAX(ts) FROM {TABLE};")
        after_max_ts = cur.fetchone()[0]

logger.info(
    "inserted_market_candle",
    extra={
        "event_type": "db.market_data_1m.insert",
        "table": TABLE,
        "symbol_raw": symbol_raw,
        "symbol": symbol,
        "ts": ts.isoformat(),
        "rows_inserted": 1,
        "ts_min": ts.isoformat(),
        "ts_max": ts.isoformat(),
        "symbol_count": 1,
        "row_returned": row,
        "before_row_count": before_count,
        "after_row_count": after_count,
        "before_max_ts": before_max_ts.isoformat() if hasattr(before_max_ts, "isoformat") else (str(before_max_ts) if before_max_ts is not None else None),
        "after_max_ts": after_max_ts.isoformat() if hasattr(after_max_ts, "isoformat") else (str(after_max_ts) if after_max_ts is not None else None),
    },
)
