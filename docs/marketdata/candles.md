# Candle Aggregation (Ticks → Multi-Timeframe OHLCV)

This module provides deterministic, TradingView-style candle aggregation over a stream of trades/ticks.

## Supported timeframes (time bars)

- `1s`, `5s`, `15s`, `30s`
- `1m`, `2m`, `3m`, `5m`, `15m`, `30m`
- `1h`, `4h`
- `1D` (alias accepted) / `1d` (canonical)

## Alignment rules (TradingView-like)

- **Intraday (seconds/minutes/hours)**: bars are aligned to **wall-clock boundaries** in `America/New_York` by default.
  - Example: `5m` bars start at `:00, :05, :10, ...` in New York local time.
  - Example: `15m` bars start at `:00, :15, :30, :45` in New York local time.
- **Daily (`1d`)**: bars align to **New York local midnight → midnight** by default.
  - If you need a “session day” (09:30 → 09:30), instantiate `CandleAggregator(..., session_daily=True)`.

Key helper:
- `floor_time(ts, timeframe, tz="America/New_York") -> bar_start_utc`
- `bar_end_utc` is computed from the next boundary in the same timezone.

## Out-of-order / lateness behavior

The aggregator uses **event-time watermarking** with a bounded lateness window:

- Configure `max_lateness_seconds` (default: `2`).
- For each `(symbol, timeframe)` the aggregator tracks the maximum tick timestamp seen (watermark).
- A tick is **dropped** if `tick.ts < (watermark - max_lateness_seconds)`.
  - Dropped ticks increment the `late_drops` counter and log a `late_drop` event.
- Bars are **finalized** when `bar.end_ts <= (watermark - max_lateness_seconds)` (or via `flush(now_ts)`).
- Once finalized, bars are **never mutated**.

## Streaming interface

Primary API:

- `CandleAggregator.ingest_tick(tick) -> list[Candle]`  
  Returns newly finalized candles (may be empty).
- `CandleAggregator.flush(now_ts) -> list[Candle]`  
  Finalizes candles older than the lateness window (useful for timers/shutdown).
- `CandleAggregator.get_open_bars() -> dict`  
  Returns open bar snapshots for debugging/ops.

## Example: 6 ticks → 1m candle

Time zone: `America/New_York` (EST in this example).

Ticks (all `SPY`):

1. `09:30:01` price `100.00` size `10`
2. `09:30:10` price `100.50` size `5`
3. `09:30:20` price `99.75` size `2`
4. `09:30:45` price `101.00` size `4`
5. `09:30:58` price `100.25` size `1`
6. `09:31:03` price `102.00` size `1`  (advances watermark; finalizes the `09:30` bar with default `max_lateness_seconds=2`)

Resulting finalized `1m` candle (`09:30:00` → `09:31:00` NY time):

```json
{
  "symbol": "SPY",
  "timeframe": "1m",
  "start_ts": "2025-12-20T14:30:00+00:00",
  "end_ts": "2025-12-20T14:31:00+00:00",
  "open": 100.0,
  "high": 101.0,
  "low": 99.75,
  "close": 100.25,
  "volume": 22,
  "trade_count": 5,
  "vwap": 100.3659090909,
  "is_final": true
}
```

Notes:
- The 6th tick is in the next minute; it is not part of the `09:30` bar.
- `close` is the last tick **by timestamp** within the bar (not arrival order).

## Optional bar types (scaffold)

Time bars are production-ready. Volume/range bars are not implemented in this module yet.

## Underlying intraday backfill (1m, 5m)

When option underlyings are missing intraday candles, use the backfill script:

- Script: `backend/streams/alpaca_underlying_intraday_backfill.py`
- Target store: `public.market_candles` (key: `(symbol, timeframe, ts_start)`)
- Scope defaults:
  - Symbols: `SPY,QQQ,IWM,AAPL,TSLA`
  - Timeframes: `1m,5m`
  - Range: last `30` NYSE trading days (regular session only)

Example command:

```bash
export DATABASE_URL="postgres://..."
export ALPACA_KEY_ID="..."
export ALPACA_SECRET_KEY="..."
export ALPACA_FEED="iex"
export ALPACA_SYMBOLS="SPY,QQQ,IWM,AAPL,TSLA"
export CANDLE_TIMEFRAMES="1m,5m"
export BACKFILL_TRADING_DAYS="30"
python3 backend/streams/alpaca_underlying_intraday_backfill.py
```

Dry-run:

```bash
DRY_RUN=1 python3 backend/streams/alpaca_underlying_intraday_backfill.py
```

Validation SQL (Postgres): find any NY session-day with an unexpected bar count:

```sql
-- 1m should have 390 bars per regular session day (09:30–16:00 NY)
SELECT
  symbol,
  timeframe,
  (ts_start AT TIME ZONE 'America/New_York')::date AS session_date_ny,
  COUNT(*) AS bars
FROM public.market_candles
WHERE symbol IN ('SPY','QQQ','IWM','AAPL','TSLA')
  AND timeframe IN ('1m','5m')
  AND (ts_start AT TIME ZONE 'America/New_York')::time >= TIME '09:30'
  AND (ts_start AT TIME ZONE 'America/New_York')::time <  TIME '16:00'
  AND (ts_start AT TIME ZONE 'America/New_York')::date >= (CURRENT_DATE - INTERVAL '60 days')
GROUP BY 1,2,3
HAVING (timeframe = '1m' AND COUNT(*) <> 390)
    OR (timeframe = '5m' AND COUNT(*) <> 78)
ORDER BY 3 DESC, 1, 2;
```

