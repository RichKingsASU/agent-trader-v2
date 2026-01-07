# Data plane (Tick Store + Candle Store + Proposal Store)

AgentTrader v2’s “data plane” is a **vendor-neutral scaffold** for persisting:

- **raw ticks/trades**
- **aggregated candles** (multi-timeframe)
- **strategy outputs** (signals/proposals)

It is designed to be scalable, queryable, and replay-friendly without forcing a specific database.

## Why a file store exists

- Enables **deterministic replay/backfill** without a DB deployment
- Works locally and can be mirrored to object storage (GCS/S3) later
- Provides a stable interface so a future backend (BigQuery/Postgres/ClickHouse) can plug in cleanly

## Default storage backend (NDJSON)

The default implementation is a partitioned NDJSON file store under `data/`:

- `data/ticks/YYYY/MM/DD/<symbol>.ndjson`
- `data/candles/<timeframe>/YYYY/MM/DD/<symbol>.ndjson`
- `data/proposals/YYYY/MM/DD/proposals.ndjson`

You can override the root directory:

- `DATA_PLANE_ROOT=/some/path`

## Enabling persistence (env flags)

All hooks are behind env flags (default OFF):

- `ENABLE_TICK_STORE=false`
- `ENABLE_CANDLE_STORE=false`
- `ENABLE_PROPOSAL_STORE=false`

When disabled, **no additional persistence** occurs.

## Replay: ticks → candles

Use the replay tool to generate candles deterministically from stored ticks:

```bash
python scripts/replay_ticks_to_candles.py \
  --symbols "SPY" \
  --start "2026-01-07T00:00:00Z" \
  --end "2026-01-08T00:00:00Z" \
  --timeframes "1m,5m,1h"
```

This reads from `FileTickStore` and writes final candles to `FileCandleStore`.

## What’s scaffold vs production-ready

- **Scaffold**:
  - interfaces in `backend/dataplane/interfaces.py`
  - file-based NDJSON backend in `backend/dataplane/file_store.py`
  - `query_*` methods are basic (sequential file scans)
- **Production-ready later**:
  - columnar Parquet output + compaction
  - concurrency control / atomic rollovers for multi-writer workloads
  - DB-backed implementations (BigQuery/Postgres/ClickHouse/etc.)

