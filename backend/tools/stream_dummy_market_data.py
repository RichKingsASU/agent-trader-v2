import os
import time
import random
from datetime import datetime, timezone

import psycopg

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env var is not set")

SYMBOL = "SPY"


def main() -> None:
    print(f"[streamer] Starting dummy market data stream into public.market_data_1m for {SYMBOL}")
    print(f"[streamer] Using DATABASE_URL={DATABASE_URL!r}")

    base_price = 500.0  # starting reference

    with psycopg.connect(DATABASE_URL) as conn:
        while True:
            try:
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

                print(
                    f"[streamer] Inserted: ts={row[0]} symbol={row[1]} "
                    f"open={row[2]:.2f} high={row[3]:.2f} low={row[4]:.2f} "
                    f"close={row[5]:.2f} volume={row[6]}"
                )
            except Exception as e:
                print(f"[streamer] ERROR: {e!r}")
                time.sleep(2.0)

            time.sleep(1.0)


if __name__ == "__main__":
    main()
