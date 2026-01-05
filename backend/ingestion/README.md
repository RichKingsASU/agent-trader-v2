# backend/ingestion

Cloud Run–friendly ingestion jobs owned by `backend/`.

## Market data ingest (Alpaca → Firestore → UI)

This job:
- Maintains an Alpaca websocket connection (auto-reconnect with exponential backoff + jitter)
- Coalesces quote updates in-memory to avoid Firestore write storms
- Applies **per-symbol throttling** + a **global token-bucket rate limit**
- Emits **JSON line** structured logs
- Writes a heartbeat to **`ops/market_ingest`** at least every 15s (configurable)
- Supports **DRY_RUN** mode (log-only, no Firestore writes)

### Required environment variables

- **Tenancy (required for UI + rules)**
  - `TENANT_ID` (writes to `tenants/{TENANT_ID}/...`)

- **Alpaca**
  - `ALPACA_KEY_ID` (or `ALPACA_API_KEY`)
  - `ALPACA_SECRET_KEY`
  - `MONITORED_SYMBOLS` (comma-separated; default: `SPY` if unset)
  - `ALPACA_DATA_FEED` (`iex` or `sip`, default `iex`)
  - Back-compat: `ALPACA_SYMBOLS` is still accepted if `MONITORED_SYMBOLS` is unset.

- **Firestore authentication**
  - In Cloud Run: use the service account attached to the service (ADC).
  - Locally: use ADC (`gcloud auth application-default login`) or `GOOGLE_APPLICATION_CREDENTIALS`.

### Multi-tenancy (required for UI visibility)

Firestore client rules in this repo deny global collection access from client SDKs; the UI subscribes under:
- `tenants/{TENANT_ID}/live_quotes/*`
- `tenants/{TENANT_ID}/ops/market_ingest`

So ingestion should be run with:
- `TENANT_ID` (preferred) or `FIRESTORE_TENANT_ID`

### Optional environment variables (recommended defaults)

- **Writes / throttling**
  - `PER_SYMBOL_MIN_INTERVAL_MS` (default `1000`)
  - `GLOBAL_WRITES_PER_SEC` (default `20`)
  - `GLOBAL_BURST` (default `40`)
  - `FLUSH_INTERVAL_MS` (default `200`)

- **Heartbeat**
  - `HEARTBEAT_INTERVAL_S` (default `15`)

- **Firestore schema**
  - `FIRESTORE_PROJECT_ID` (optional; otherwise uses ADC default project)
  - `FIRESTORE_LIVE_QUOTES_COLLECTION` (default `live_quotes`)
  - Back-compat: `FIRESTORE_LATEST_COLLECTION` is still accepted if `FIRESTORE_LIVE_QUOTES_COLLECTION` is unset.

- **Reconnect behavior**
  - `RECONNECT_BACKOFF_BASE_S` (default `1`)
  - `RECONNECT_BACKOFF_MAX_S` (default `60`)

- **Bounded runs (useful for testing)**
  - `STOP_AFTER_SECONDS` (no default; if set, stops after N seconds)

### Run (local)

From repo root:

```bash
python -m backend.ingestion.market_data_ingest
```

Dry run (no Firestore writes):

```bash
TENANT_ID=local DRY_RUN=1 python -m backend.ingestion.market_data_ingest
```

### Smoke check (60s)

Runs the ingest for 60 seconds and exits 0/1 with PASS/FAIL output.
- With `DRY_RUN=0`, requires at least one successful Firestore write (quote and/or heartbeat).
- With `DRY_RUN=1`, requires at least one logged “would write” action.

```bash
TENANT_ID=local python -m backend.ingestion.smoke_check_market_data_ingest
```

