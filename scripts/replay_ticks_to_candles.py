from __future__ import annotations

import argparse
import os
from collections import defaultdict
from datetime import datetime
from typing import Any

from backend.common.timeutils import parse_timestamp
from backend.dataplane.file_store import FileCandleStore, FileTickStore
from backend.marketdata.candles.aggregator import CandleAggregator


def _env_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def main() -> None:
    p = argparse.ArgumentParser(description="Replay stored ticks into candles (deterministic backfill).")
    p.add_argument("--symbols", default=os.getenv("ALPACA_SYMBOLS", ""), help="Comma-separated symbols to replay")
    p.add_argument("--start", required=True, help="UTC start timestamp (ISO8601 or epoch)")
    p.add_argument("--end", required=True, help="UTC end timestamp (ISO8601 or epoch)")
    p.add_argument(
        "--timeframes",
        default=os.getenv("CANDLE_TIMEFRAMES", "1m,5m,15m,1h,1d"),
        help="Comma-separated timeframes (e.g. 1m,5m,1h)",
    )
    p.add_argument("--lateness-seconds", type=int, default=0, help="Aggregation lateness window (default: 0)")
    args = p.parse_args()

    symbols = [s.strip() for s in (args.symbols or "").split(",") if s.strip()]
    if not symbols:
        raise SystemExit("No symbols provided. Use --symbols or set ALPACA_SYMBOLS.")

    start_utc: datetime = parse_timestamp(args.start)
    end_utc: datetime = parse_timestamp(args.end)

    tfs = _env_list("CANDLE_TIMEFRAMES", args.timeframes)
    if not tfs:
        raise SystemExit("No timeframes provided.")

    tick_store = FileTickStore()
    candle_store = FileCandleStore()

    agg = CandleAggregator(
        timeframes=tfs,
        lateness_seconds=int(args.lateness_seconds),
        emit_updates=False,  # deterministic backfill: finals-only
    )

    batch: dict[tuple[str, str], list[Any]] = defaultdict(list)
    batch_max = 1000

    def flush_batches() -> None:
        for (sym, tf), candles in list(batch.items()):
            if candles:
                candle_store.write_candles(sym, tf, candles)
            batch[(sym, tf)].clear()

    for sym in symbols:
        ticks = tick_store.query_ticks(sym, start_utc, end_utc)
        for t in ticks:
            event = {
                "symbol": sym,
                "timestamp": t.get("timestamp", t.get("ts")),
                "price": t.get("price"),
                "size": t.get("size"),
            }
            emitted = agg.ingest(event)
            finals = [c for c in emitted if getattr(c, "is_final", False)]
            for c in finals:
                batch[(c.symbol, c.timeframe)].append(c)
                if len(batch[(c.symbol, c.timeframe)]) >= batch_max:
                    candle_store.write_candles(c.symbol, c.timeframe, batch[(c.symbol, c.timeframe)])
                    batch[(c.symbol, c.timeframe)].clear()

    # Finalize any remaining states at end_utc and write.
    for c in agg.flush(end_utc):
        if getattr(c, "is_final", False):
            batch[(c.symbol, c.timeframe)].append(c)

    flush_batches()


if __name__ == "__main__":
    main()

