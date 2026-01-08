# Live Quotes End-to-End Flow (Production Readiness)

This doc describes the **live quote pipeline** from Alpaca to the UI, the **heartbeat contract**, and the **stability checks** to validate production readiness.

## End-to-end flow

### 1) Alpaca → Backend ingestion

- **Producer**: Alpaca market data websocket (quotes stream).
- **Backend job**: `backend/ingestion/market_data_ingest.py`
  - Subscribes to Alpaca quotes for `MONITORED_SYMBOLS` / `ALPACA_SYMBOLS`
  - Coalesces per-symbol updates in-memory (prevents “write storms”)
  - Enforces throttles:
    - **Per-symbol** min write interval (default `1s`)
    - **Global** token-bucket rate limit (default `20 writes/sec`, burst `40`)
  - Emits structured JSON logs:
    - `event_type=quote` on each received/simulated quote tick
    - `event_type=firestore_write` on each write intent / write
    - `event_type=heartbeat` on heartbeat writes
  - Auto-reconnects with exponential backoff (prevents tight restart loops)

### 2) Backend → Firestore

Firestore **client security rules** in this repo require **tenant scoping**:
- Client apps may read/write only under: `tenants/{tenantId}/...`
- Global collections are **denied** to client SDKs.

The ingestion job therefore writes to:

- **Latest quotes**:
  - `tenants/{TENANT_ID}/live_quotes/{SYMBOL}`
- **Heartbeat**:
  - `tenants/{TENANT_ID}/ops/market_ingest`

Notes:
- `TENANT_ID` is required for UI visibility (or `FIRESTORE_TENANT_ID` as back-compat).
- The writer normalizes timestamps to Firestore `Timestamp` types. Today the ingestion job guarantees **`ts`** on both quote docs and heartbeat docs; the UI also accepts `updated_at` / `last_update_ts` / `last_heartbeat_at` as back-compat.
- Quote field naming is intentionally tolerant:
  - **Canonical** (current ingest): `bid`, `ask`, `price`, `ts`
  - **Legacy/UI back-compat**: `bid_price`, `ask_price`, `last_trade_price`, `last_update_ts`

### 3) Firestore → UI

- **Hook**: `frontend/src/hooks/useLiveQuotes.ts`
  - Subscribes to:
    - `tenants/{tenantId}/live_quotes` (collection listener)
    - `tenants/{tenantId}/ops/market_ingest` (doc listener)
  - Computes status from heartbeat freshness:
    - **LIVE**: heartbeat age ≤ `heartbeatStaleAfterSeconds` (default `30s`)
    - **STALE**: heartbeat age > threshold
    - **OFFLINE**: no heartbeat / subscription error / not authenticated
- **Widget**: `frontend/src/components/LiveQuotesWidget.tsx`
  - Renders quotes and LIVE/STALE/OFFLINE badge

## Required configuration (production)

### Backend ingestion env

- **Tenant scoping**
  - `TENANT_ID` (preferred) or `FIRESTORE_TENANT_ID`
- **Alpaca**
  - `APCA_API_KEY_ID`
  - `APCA_API_SECRET_KEY`
  - `APCA_API_BASE_URL`
  - `MONITORED_SYMBOLS` (comma-separated; default `SPY`)
  - `ALPACA_DATA_FEED` (`iex` or `sip`, default `iex`)
- **Firestore / Firebase Admin (ADC)**
  - In Cloud Run: service account attached to the service
  - Locally: ADC (`gcloud auth application-default login`) or `GOOGLE_APPLICATION_CREDENTIALS`
  - Optional: `FIRESTORE_PROJECT_ID` / `FIREBASE_PROJECT_ID`

### Frontend env

- Firebase web config (see `frontend/src/firebase.ts` usage)
- User auth token must include `tenant_id` claim and membership doc must exist:
  - `tenants/{tenantId}/users/{uid}`

## Operational contracts

### Heartbeat doc

Path:
- `tenants/{TENANT_ID}/ops/market_ingest`

Fields (minimum):
- `ts`: timestamp (writer time) *(canonical in current ingest)*
- `status`: `running` (or similar)
- `last_symbol`: last symbol observed (optional)
- `dry_run`: boolean (optional)

Write cadence:
- Recommended every **10–30 seconds** (default is `15s`).

### Quote doc

Path:
- `tenants/{TENANT_ID}/live_quotes/{SYMBOL}`

Fields (typical):
- `symbol`, `bid`, `ask`, `price`
- `ts` (event time / received time; canonical timestamp field)
- `source` (e.g. `alpaca`)

## Stability checks (what “production-stable” means)

### Backend ingest

- **No tight reconnect loops**:
  - reconnect uses bounded exponential backoff
- **Write storm protection**:
  - coalescing + per-symbol throttling + global token-bucket
- **Heartbeat always updates**:
  - independent loop from quote processing
- **Graceful shutdown**:
  - responds to SIGTERM/SIGINT (important for Cloud Run)

### Frontend

- **Build is clean** and dev server boots without runtime errors
- **LIVE/STALE/OFFLINE** reflects heartbeat freshness
- Quotes populate and update as Firestore documents change

## Local smoke tests

### Backend DRY_RUN (no Alpaca creds required)

Simulates deterministic quotes + heartbeat and exits with PASS/FAIL:

```bash
TENANT_ID=local DRY_RUN=1 python3 -m backend.ingestion.smoke_check_market_data_ingest
```

### Frontend dev server (brief boot)

```bash
cd frontend
npm install
npm run dev
```

## Troubleshooting quick hits

- **UI shows OFFLINE**
  - Check auth token contains `tenant_id` and membership doc exists under `tenants/{tenantId}/users/{uid}`
  - Verify Firestore rules are deployed and the app points to the right project
- **UI shows STALE**
  - Ingest is not updating `tenants/{tenantId}/ops/market_ingest` at least every ~30s
  - Check ingest logs for heartbeat errors
- **Quotes missing but heartbeat LIVE**
  - Ingest is running but not receiving quotes for configured symbols (market closed / bad feed / symbol list)
  - Check ingest logs for `event_type=quote` and `event_type=firestore_write`

