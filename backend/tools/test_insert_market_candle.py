import os
import random
from datetime import datetime, timezone

import psycopg

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is not set")

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

with psycopg.connect(DATABASE_URL) as conn:
    with conn.cursor() as cur:
        cur.execute(insert_sql, (symbol, ts, open_, high, low, close, volume))
        row = cur.fetchone()

print("Inserted row into public.market_data_1m:")
print(row)
