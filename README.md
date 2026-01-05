# AgentTrader V2 (Alpaca + Firebase)

AgentTrader is a monorepo for Alpaca market ingestion + a Lovable-generated UI, backed by Firebase (Firestore).

## Repo layout

- **`/backend`**: Python services + ingestion jobs
- **`/frontend`**: Vite + React UI (Lovable export)
- **`/infra`**: Dockerfiles + Cloud Build configs
- **`/scripts`**: local/dev automation scripts (no secrets)

## Local development (one command)

### Prereqs

- **Python**: `python3` + `pip3`
- **Node**: `node` + `npm`
- **GCloud** (for Firebase Admin / Firestore auth):
  - Install the Google Cloud SDK, then run:

```bash
gcloud auth application-default login
```

If you prefer a local service account JSON (not recommended), see `docs/credentials.md`.

### 1) Configure env (names only; no secrets committed)

Backend (Firestore):

- Set one of:
  - `FIREBASE_PROJECT_ID` (preferred)
  - `FIRESTORE_PROJECT_ID` (back-compat)
  - `GOOGLE_CLOUD_PROJECT`
- Credentials:
  - Preferred: `gcloud auth application-default login` (ADC)
  - Or set `GOOGLE_APPLICATION_CREDENTIALS` to a local JSON path (**do not commit**)
  - Or set `FIRESTORE_EMULATOR_HOST` to use the Firestore emulator (no credentials needed)

Helper (optional):

```bash
chmod +x ./scripts/set_google_application_credentials.sh
./scripts/set_google_application_credentials.sh "$HOME/secrets/service-account-key.json"
```

Frontend (Vite):

- Create `frontend/.env.local` with:
  - `VITE_FIREBASE_API_KEY`
  - `VITE_FIREBASE_AUTH_DOMAIN`
  - `VITE_FIREBASE_PROJECT_ID`
  - `VITE_FIREBASE_APP_ID`
  - (optional) `VITE_FIREBASE_STORAGE_BUCKET`
  - (optional) `VITE_FIREBASE_MESSAGING_SENDER_ID`
  - (optional) `VITE_STREAMER_URL` (for the LiveTicker EventSource stream)

### 2) Run everything

From repo root:

```bash
chmod +x ./scripts/dev_*.sh
./scripts/dev_all.sh
```

Or run separately:

```bash
./scripts/dev_backend.sh
./scripts/dev_frontend.sh
```

## Backend: market data ingestion (Firestore)

The primary ingestion entrypoint is:

- `python3 -m backend.ingestion.market_data_ingest`

**Environment variables (names only):**

- **Alpaca**
  - `ALPACA_KEY_ID`
  - `ALPACA_SECRET_KEY`
  - `ALPACA_SYMBOLS` (comma-separated, e.g. `SPY,IWM,QQQ`)
  - `ALPACA_DATA_FEED` (`iex` or `sip`)
- **Firebase / Firestore**
  - `FIRESTORE_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`)
  - `FIRESTORE_LATEST_COLLECTION` (default: `market_latest`)
- **Runtime**
  - `DRY_RUN` (`1` to simulate writes)
  - `STOP_AFTER_SECONDS` (optional)

## Frontend: Lovable UI (Vite)

From `frontend/`:

```bash
npm install
npm run dev
```

Build (CI-friendly):

```bash
npm run build
```

Firebase initialization is centralized in `frontend/src/firebase.ts`.
