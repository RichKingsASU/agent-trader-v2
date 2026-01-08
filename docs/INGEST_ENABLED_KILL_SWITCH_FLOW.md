# `INGEST_ENABLED` kill-switch flow (end-to-end)

This repo uses a **soft ingest pause switch** (`INGEST_ENABLED`) so ingestion producers can be halted/resumed without redeploying.

## Flow diagram

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Operator / Platform                                                         │
│  - sets Cloud Run env var: INGEST_ENABLED=0|1                                │
│  - (optional) sets file mount: INGEST_ENABLED_FILE=/path/to/flag             │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Producer: market-ingest (Cloud Run)                                          │
│  backend.ingestion.market_data_ingest.MarketDataIngestor.run()               │
│   - polls get_ingest_enabled_state() every INGEST_ENABLED_POLL_S (default 5) │
│   - on transition: logs ingest_switch {halted|resumed} once                  │
│   - when paused: stops Alpaca websocket + skips reconnect loop               │
│   - heartbeat continues, writes status="paused" + ingest_enabled fields      │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ Firestore heartbeat (always, even when paused)
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Firestore                                                                    │
│  tenants/{TENANT_ID}/ops/market_ingest                                       │
│   - status: "running" | "paused"                                             │
│   - ts: heartbeat timestamp                                                  │
│   - ingest_enabled: bool                                                     │
│   - ingest_enabled_source: "env:INGEST_ENABLED" | "file:..." | null          │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ Consumers (tolerate zero producers)                                          │
│  - UI / APIs read heartbeat; missing/old heartbeat is treated as stale       │
│  - push-based consumers keep /livez healthy even with zero incoming pushes   │
│    (background loop heartbeat task)                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Where `INGEST_ENABLED` is enforced

- **Shared helper**: `backend/common/ingest_switch.py`
  - `INGEST_ENABLED` (env): `"0"/"false"/"off"` => paused; default enabled if unset.
  - `INGEST_ENABLED_FILE` (env): optional file path whose first line is parsed similarly.
- **Market ingest producer**: `backend/ingestion/market_data_ingest.py`
  - Logs `ingest_switch` when ingestion halts/resumes.
  - Stops the Alpaca websocket while paused to avoid holding connections.

## Deployment wiring

- **Cloud Run env template**: `infra/cloudrun/env/market_ingest.env.yaml.example`
- **Cloud Run service template**: `infra/cloudrun/services/market-ingest.service.yaml`

