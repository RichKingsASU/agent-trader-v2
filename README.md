# AgentTrader V2 (Alpaca + Firebase)

AgentTrader is a monorepo for Alpaca market ingestion + a Lovable-generated UI, backed by Firebase (Firestore).

## 🔒 Enforcement & Safety Guarantees (AgentTrader v2)

AgentTrader v2 is a **production-locked, institutional trading platform**.
All development, automation, and agent behavior is governed by the rules below.

### 🚫 Execution Status
- **Trading execution is DISABLED**
- No broker APIs are called
- Execution agents are permanently scaled to `0`
- `AGENT_MODE=EXECUTE` is forbidden in all manifests

### 🛑 Safety Controls
- Global kill-switch defaults to SAFE
- Marketdata staleness halts all strategy activity
- No strategy may execute without explicit human authorization
- All execution pathways are scaffold-only and disabled

### 🧠 Agent Constraints
Agents MAY:
- Generate reports and audit artifacts
- Emit strategy proposals (non-executing)
- Run readiness and safety checks
- Capture last-known-good snapshots
- Perform read-only operational tasks

Agents MUST NOT:
- Change `AGENT_MODE`
- Flip kill-switches
- Deploy to production
- Enable execution
- Modify locked artifacts

### 📋 Engineering Guarantees
- No `:latest` images anywhere
- Identity + intent logging is mandatory
- All logs are structured JSON
- All deploys are auditable and replayable
- Fail-safe defaults are enforced everywhere

### 🔐 Change Control
Any action that would:
- enable execution
- weaken safety defaults
- introduce new agents
- modify kill-switch behavior

**requires a formal unlock ceremony**, documented approvals, and a new production lock.

### 🧾 Auditability
The system continuously produces:
- readiness reports
- deploy reports
- config snapshots
- proposal logs
- postmortem replays

These artifacts form the system’s permanent audit trail.

> **This repo is governed, not experimental.**
> If a change cannot be explained to an auditor, it does not belong here.

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
