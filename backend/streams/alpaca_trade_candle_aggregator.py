from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import asyncpg
from alpaca.data.enums import DataFeed
from alpaca.data.live.stock import StockDataStream

from backend.common.timeutils import ensure_aware_utc, utc_now
from backend.dataplane.file_store import FileCandleStore, FileTickStore
from backend.marketdata.candles.aggregator import CandleAggregator
from backend.marketdata.candles.models import EmittedCandle
from backend.marketdata.candles.timeframes import SUPPORTED_TIMEFRAMES
from backend.streams.alpaca_env import load_alpaca_env
from backend.utils.ops_markers import OpsDB

logger = logging.getLogger(__name__)


def _env_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


def _env_bool(name: str, default: str = "false") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in {"1", "true", "yes", "y"}


def _parse_feed(value: str) -> DataFeed:
    v = (value or "").strip().lower()
    if v == "sip":
        return DataFeed.SIP
    # default (and matches existing scripts): IEX
    return DataFeed.IEX


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    symbols: list[str]
    timeframes: list[str]
    lateness_seconds: int
    tz_market: str
    session_daily: bool
    feed: DataFeed
    flush_interval_sec: float
    db_batch_max: int

    @classmethod
    def from_env(cls) -> "Settings":
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("Missing required env var: DATABASE_URL")
        symbols = _env_list("ALPACA_SYMBOLS", "SPY,IWM,QQQ")

        timeframes = _env_list(
            "CANDLE_TIMEFRAMES",
            ",".join(
                [
                    "15s",
                    "1m",
                    "5m",
                    "15m",
                    "1h",
                    "1d",
                ]
            ),
        )
        lateness_seconds = int(os.getenv("CANDLE_LATENESS_SECONDS", "5"))
        tz_market = os.getenv("CANDLE_MARKET_TZ", "America/New_York")
        session_daily = os.getenv("CANDLE_SESSION_DAILY", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
        }
        feed = _parse_feed(os.getenv("ALPACA_FEED", "iex"))
        flush_interval_sec = float(os.getenv("CANDLE_FLUSH_INTERVAL_SEC", "1.0"))
        db_batch_max = int(os.getenv("CANDLE_DB_BATCH_MAX", "500"))

        return cls(
            database_url=database_url,
            symbols=symbols,
            timeframes=timeframes,
            lateness_seconds=lateness_seconds,
            tz_market=tz_market,
            session_daily=session_daily,
            feed=feed,
            flush_interval_sec=flush_interval_sec,
            db_batch_max=db_batch_max,
        )


class MarketCandlesWriter:
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    @classmethod
    async def create(cls, database_url: str) -> "MarketCandlesWriter":
        pool = await asyncpg.create_pool(database_url)
        return cls(pool)

    async def upsert_many(self, candles: Iterable[EmittedCandle]) -> None:
        rows = [
            (
                c.symbol,
                c.timeframe,
                ensure_aware_utc(c.ts_start_utc),
                ensure_aware_utc(c.ts_end_utc),
                float(c.open),
                float(c.high),
                float(c.low),
                float(c.close),
                int(c.volume),
                None if c.vwap is None else float(c.vwap),
                None if c.trade_count is None else int(c.trade_count),
                bool(c.is_final),
            )
            for c in candles
        ]
        if not rows:
            return

        sql = """
        INSERT INTO public.market_candles
          (symbol, timeframe, ts_start, ts_end, open, high, low, close, volume, vwap, trade_count, is_final)
        VALUES
          ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (symbol, timeframe, ts_start) DO UPDATE SET
          ts_end = EXCLUDED.ts_end,
          open = EXCLUDED.open,
          high = EXCLUDED.high,
          low = EXCLUDED.low,
          close = EXCLUDED.close,
          volume = EXCLUDED.volume,
          vwap = EXCLUDED.vwap,
          trade_count = EXCLUDED.trade_count,
          is_final = EXCLUDED.is_final,
          updated_at = now();
        """

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(sql, rows)


async def _db_consumer(queue: asyncio.Queue[EmittedCandle], writer: MarketCandlesWriter, *, batch_max: int) -> None:
    buf: list[EmittedCandle] = []
    while True:
        try:
            item = await queue.get()
            buf.append(item)

            while len(buf) < batch_max:
                try:
                    item2 = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                buf.append(item2)

            await writer.upsert_many(buf)
            for _ in range(len(buf)):
                queue.task_done()
            buf.clear()
        except Exception:
            logger.exception("market_candles db consumer error")
            # Best effort: drop current buffer to avoid infinite retries clogging the stream.
            for _ in range(len(buf)):
                queue.task_done()
            buf.clear()
            await asyncio.sleep(1)


async def _periodic_flush(
    agg: CandleAggregator,
    queue: asyncio.Queue[EmittedCandle],
    *,
    interval_sec: float,
    candle_store: FileCandleStore | None = None,
) -> None:
    while True:
        await asyncio.sleep(interval_sec)
        try:
            now = utc_now()
            flushed = agg.flush(now)
            if candle_store is not None:
                try:
                    finals = [c for c in flushed if getattr(c, "is_final", False)]
                    if finals:
                        grouped: dict[tuple[str, str], list[EmittedCandle]] = {}
                        for c in finals:
                            grouped.setdefault((c.symbol, c.timeframe), []).append(c)
                        for (sym, tf), batch in grouped.items():
                            candle_store.write_candles(sym, tf, batch)
                except Exception:
                    logger.exception("candle store write failed (flush loop)")

            for c in flushed:
                queue.put_nowait(c)
        except Exception:
            logger.exception("candle flush loop error")


async def _periodic_ops(agg: CandleAggregator, *, interval_sec: float = 30.0) -> None:
    """
    Writes ops watermark meta for observability (best-effort).
    """
    try:
        ops = OpsDB()
    except Exception:
        logger.info("ops markers disabled (DATABASE_URL not set or driver missing)")
        return

    while True:
        await asyncio.sleep(interval_sec)
        try:
            snap = agg.ops_snapshot()
            ops.upsert_watermark(
                pipeline="alpaca_trade_candles",
                partition_key="global",
                last_event_time=None,
                last_received_at=datetime.now(timezone.utc),
                meta=snap,
            )
        except Exception:
            logger.exception("ops markers error")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    cfg = Settings.from_env()
    unsupported = sorted(set(cfg.timeframes) - set(SUPPORTED_TIMEFRAMES))
    if unsupported:
        raise RuntimeError(f"Unsupported timeframes requested: {unsupported}. Supported: {list(SUPPORTED_TIMEFRAMES)}")

    if not cfg.symbols:
        raise RuntimeError("ALPACA_SYMBOLS resolved to empty list")

    alpaca = load_alpaca_env()
    logger.info(
        "Starting Alpaca trade candle aggregator | symbols=%s | timeframes=%s | lateness=%ss | feed=%s",
        ",".join(cfg.symbols),
        ",".join(cfg.timeframes),
        cfg.lateness_seconds,
        cfg.feed.value if hasattr(cfg.feed, "value") else str(cfg.feed),
    )

    agg = CandleAggregator(
        timeframes=cfg.timeframes,
        lateness_seconds=cfg.lateness_seconds,
        tz_market=cfg.tz_market,
        session_daily=cfg.session_daily,
        emit_updates=True,
    )

    enable_tick_store = _env_bool("ENABLE_TICK_STORE", "false")
    enable_candle_store = _env_bool("ENABLE_CANDLE_STORE", "false")
    tick_store = FileTickStore() if enable_tick_store else None
    candle_store = FileCandleStore() if enable_candle_store else None

    writer = await MarketCandlesWriter.create(cfg.database_url)
    out_q: asyncio.Queue[EmittedCandle] = asyncio.Queue(maxsize=cfg.db_batch_max * 4)

    # Start DB writer + periodic flush loops
    tasks = [
        asyncio.create_task(_db_consumer(out_q, writer, batch_max=cfg.db_batch_max)),
        asyncio.create_task(_periodic_flush(agg, out_q, interval_sec=cfg.flush_interval_sec, candle_store=candle_store)),
        asyncio.create_task(_periodic_ops(agg, interval_sec=30.0)),
    ]

    wss_client = StockDataStream(alpaca.key_id, alpaca.secret_key, feed=cfg.feed)

    async def trade_handler(data: Any) -> None:
        # Alpaca trade objects have .symbol/.price/.size/.timestamp
        event = {
            "symbol": getattr(data, "symbol", None),
            "price": getattr(data, "price", None),
            "size": getattr(data, "size", None),
            "timestamp": getattr(data, "timestamp", None),
        }

        if tick_store is not None:
            try:
                sym = str(event.get("symbol") or "").strip().upper()
                if sym:
                    tick_store.write_ticks(sym, [event])
            except Exception:
                logger.exception("tick store write failed")

        candles = agg.ingest(event)

        if candle_store is not None:
            try:
                finals = [c for c in candles if getattr(c, "is_final", False)]
                if finals:
                    grouped: dict[tuple[str, str], list[EmittedCandle]] = {}
                    for c in finals:
                        grouped.setdefault((c.symbol, c.timeframe), []).append(c)
                    for (sym, tf), batch in grouped.items():
                        candle_store.write_candles(sym, tf, batch)
            except Exception:
                logger.exception("candle store write failed")

        for c in candles:
            try:
                out_q.put_nowait(c)
            except asyncio.QueueFull:
                # Backpressure: drop updates but keep finals (best-effort).
                if c.is_final:
                    await out_q.put(c)

        if agg.candles_emitted_update % 5000 == 0 and agg.candles_emitted_update > 0:
            logger.info("candle agg snapshot: %s", agg.ops_snapshot())

    logger.info("Subscribing to trades for: %s", ",".join(cfg.symbols))
    wss_client.subscribe_trades(trade_handler, *cfg.symbols)

    try:
        await wss_client.run()
    finally:
        # Best-effort shutdown flush
        try:
            flushed = agg.flush(utc_now())
            if candle_store is not None:
                try:
                    finals = [c for c in flushed if getattr(c, "is_final", False)]
                    if finals:
                        grouped: dict[tuple[str, str], list[EmittedCandle]] = {}
                        for c in finals:
                            grouped.setdefault((c.symbol, c.timeframe), []).append(c)
                        for (sym, tf), batch in grouped.items():
                            candle_store.write_candles(sym, tf, batch)
                except Exception:
                    logger.exception("candle store write failed (shutdown flush)")

            for c in flushed:
                out_q.put_nowait(c)
            await out_q.join()
        except Exception:
            logger.exception("shutdown flush failed")

        for t in tasks:
            t.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

