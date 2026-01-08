# AgentTrader V2 (Pre-Firebase Stabilization)

AgentTrader is a monorepo for Alpaca market ingestion + a Vite/React UI.

## Current Status: Pre-Firebase Stabilization

- **Goal**: stabilize and sanitize the codebase before starting any Firebase migration work.
- **Non-goals**: no feature changes, no Firebase rollout, no API redesign.
- **Local run**: the frontend runs in **local mode by default** (no external SaaS required). Firebase config is optional.

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

## Recommended Workflow

For common operational tasks (e.g., local development, testing, building), it is highly recommended to use the `make` utility. This provides a unified, self-documenting interface to the underlying scripts, improving clarity and determinism.

**Note:** Using `make` targets does NOT change the runtime behavior of the application or alter any existing safety controls. Execution remains DISABLED.

To see available commands:

```bash
make help
```

## CI Safety Guard

This repository includes a `scripts/ci_safety_guard.sh` script that runs automatically in the CI/CD pipeline. This guard is a read-only, non-destructive check to prevent high-risk configurations from being committed or deployed.

For the full list of CI assumptions and guard invariants, see `docs/CI_CONTRACT.md`.

**Purpose:** To provide an automated safety net against common operational errors and enforce non-negotiable architectural rules.

**The guard will fail the build if it detects:**
1.  **`:latest` image tags:** All container images must have a specific version or SHA hash.
2.  **`AGENT_MODE` set to `EXECUTE`:** Production execution is disabled at the code level.
3.  **Execution agent `replicas > 0`:** Execution agents must be scaled to zero by default.

**How to Fix Failures:**
If the safety guard fails your build, read the error message carefully. It will point to the exact file and line that caused the violation. Correct the configuration in that file and commit the change.

## Repo layout

- **`/backend`**: Python services + ingestion jobs
- **`/frontend`**: Vite + React UI
- **`/infra`**: Dockerfiles + Cloud Build configs
- **`/scripts`**: local/dev automation scripts (no secrets)

## Local development (one command)

### Prereqs

- **Python**: `python3` + `pip3`
- **Node**: `node` + `npm`
- **GCloud** (optional; only if you enable Firebase locally):
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
  - `APCA_API_KEY_ID`
  - `APCA_API_SECRET_KEY`
  - `APCA_API_BASE_URL`
  - `ALPACA_SYMBOLS` (comma-separated, e.g. `SPY,IWM,QQQ`)
  - `ALPACA_DATA_FEED` (`iex` or `sip`)
- **Firebase / Firestore**
  - `FIRESTORE_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`)
  - `FIRESTORE_LATEST_COLLECTION` (default: `market_latest`)
- **Runtime**
  - `DRY_RUN` (`1` to simulate writes)
  - `STOP_AFTER_SECONDS` (optional)

## Frontend: UI (Vite)

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

## vNEXT: repo-wide non-invasive confirmation

A repo-wide scan shows **no vNEXT-labeled runtime code** (outside vendored dependencies), so vNEXT introduces:
- no imports from live-trading execution code
- no side effects
- no background threads
- no network calls