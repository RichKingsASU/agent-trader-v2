# Data plane partitioning + retention plan (scaffold)

This document defines a vendor-neutral partitioning plan for AgentTrader v2’s “institutional data plane”.
The intent is to keep ingestion/replay deterministic **without requiring a database deployment**.

## Recommended partition keys

- **Primary**: `date (UTC)` + `symbol` (+ `timeframe` for candles)
- **Paths (file backend)**:
  - **ticks**: `data/ticks/YYYY/MM/DD/<symbol>.ndjson`
  - **candles**: `data/candles/<timeframe>/YYYY/MM/DD/<symbol>.ndjson`
  - **proposals**: `data/proposals/YYYY/MM/DD/proposals.ndjson`

## Retention recommendations

- **ticks/trades**:
  - **hot**: 30–90 days (fast local disk / “hot” object tier)
  - **cold**: archive older partitions (compressed NDJSON / Parquet later)
- **candles**:
  - 1–2 years (small footprint; replay-friendly)
- **proposals**:
  - permanent (audit artifact + research replay)

## Future DB indexing recommendations

When you move to a database (BigQuery/Postgres/ClickHouse/etc.), index or cluster on:

- **ticks**: `(symbol, ts)` (and optionally `exchange` / `venue` if present)
- **candles**: `(symbol, timeframe, ts_start)` (or `(timeframe, ts_start)` for scans)
- **proposals**: `(strategy_id|strategy_name, created_at)` and optionally `(symbol, created_at)`

## Notes

- The file layout is designed to map 1:1 onto common partitioning systems (Hive-style partitions / dataset sharding).
- NDJSON is required for portability; Parquet can be added later for columnar analytics once dependencies are decided.

