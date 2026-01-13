## Historical seed runbook (paper-only)

Goal: seed **last 30 trading days of 1m bars** into the canonical storage target for tomorrow’s paper run.

This repo is **paper-only**. Seeding enforces:
- `TRADING_MODE=paper` (hard lock)
- `APCA_API_BASE_URL=https://paper-api.alpaca.markets` (hard assertion)
- `AGENT_MODE` must be explicitly set and must not allow execution

### Canonical ingestion/backfill modules + storage targets

- **Historical bars backfill**: `backend/streams/alpaca_backfill_bars.py`
  - **Writes to**: Postgres table `public.market_data_1m`
  - **Upsert key**: `(ts, symbol)` (idempotent gap-fill)
- **Short-window bars ingest**: `backend/streams/alpaca_bars_ingest.py` (small recent window)
- **Live quotes ingest**: `backend/ingestion/market_data_ingest.py` (Firestore latest quotes; not historical bars)

### Required env vars

```bash
export AGENT_MODE=OFF
export TRADING_MODE=paper

export APCA_API_KEY_ID="..."
export APCA_API_SECRET_KEY="..."
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"

# Postgres (required for historical seeding)
export DATABASE_URL="postgresql://..."
```

### Install deps (once)

```bash
pip install -r backend/requirements.txt
```

### Seed last 30 trading days of 1m bars (recommended tonight)

```bash
export ALPACA_SYMBOLS="SPY,QQQ,AAPL"
export ALPACA_FEED="iex"
export ALPACA_BACKFILL_TRADING_DAYS="30"

python -m backend.streams.alpaca_backfill_bars
```

Notes:
- **Timeframe** is currently fixed to **1Min** and writes into `public.market_data_1m`.
- **Gap-fill** behavior is done via `ON CONFLICT (ts, symbol) DO UPDATE ...` (safe to re-run).

### Where results are written / what to verify

- **Primary output**: Postgres `public.market_data_1m`
- **Success signal**: logs like `SPY: upserted <N> bars from <start> to <end>`

To declare “ready for tomorrow”:
- **Preflight passes** (no `PREFLIGHT_FAILED`)
- **Backfill logs show nonzero upserts** for the target symbols
- **A quick DB spot-check** (example SQL):

```sql
SELECT symbol, max(ts) AS latest_ts, count(*) AS rows_last_2d
FROM public.market_data_1m
WHERE ts >= now() - interval '2 days'
  AND symbol IN ('SPY','QQQ','AAPL')
GROUP BY symbol
ORDER BY symbol;
```

