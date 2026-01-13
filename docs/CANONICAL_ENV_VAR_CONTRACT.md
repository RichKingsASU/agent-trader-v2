# Canonical Environment Variable Contract (AgentTrader v2)

Mission: establish a single **canonical env var contract** for runtime services, including **implicit hard-fail** variables, **alias normalization**, and a gap analysis versus shipped `.env.example` + infra templates.

## Scope & sources (authoritative)

Enumerated from:
- `backend/common/config.py` (central contract registry)
- `backend/common/agent_mode_guard.py` (agent-mode + paper-trading hard lock; hard-fails)
- Execution gating:
  - `backend/execution_agent/gating.py` (strict startup gate; hard-fails)
  - `backend/common/kill_switch.py` (execution halt switch)
  - `backend/common/execution_confirm.py` (future live-confirm token)
- Firebase / PubSub usage:
  - `backend/persistence/firebase_client.py` (ADC + project resolution; hard-fails)
  - `backend/ingestion/pubsub_event_ingestion_service.py` (ingest heartbeat apply)
  - `cloudrun_ingestor/main.py` + `cloudrun_consumer/main.py` (Cloud Run runtime config)

## Canonical naming + alias normalization

### Alpaca credentials (canonical)
Use the **official Alpaca SDK** env vars:
- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`
- `APCA_API_BASE_URL` (e.g. `https://paper-api.alpaca.markets`)

Accepted aliases (normalized to canonical at runtime via `backend/common/env.py`):
- `ALPACA_API_KEY` → `APCA_API_KEY_ID`
- `ALPACA_API_KEY_ID` → `APCA_API_KEY_ID`
- `ALPACA_SECRET_KEY` / `ALPACA_API_SECRET_KEY` → `APCA_API_SECRET_KEY`
- `ALPACA_TRADING_HOST` / `ALPACA_API_BASE_URL` / `ALPACA_API_URL` → `APCA_API_BASE_URL`

### GCP project id (canonical per-service)
This repo uses **multiple canonical project envs** by service:
- Cloud Run ingestion/consumer use `GCP_PROJECT` (and normalize from common GCP aliases).
- Most Firebase/Firestore code uses `FIREBASE_PROJECT_ID` (and falls back to `FIRESTORE_PROJECT_ID` / `GOOGLE_CLOUD_PROJECT` / ADC).

## Master environment variable table

Legend:
- **Required (local)**: must be set to run locally (or CI) without crashing.
- **Required (prod)**: must be set in production deployment for the service to start correctly.
- **Optional**: defaulted or feature-toggled.
- **Forbidden in prod**: should not be present in production (keyfile patterns / emulator flags).

| Variable | Canonical meaning | Required (local) | Required (prod) | Optional | Forbidden in prod | Notes / validation |
|---|---:|---:|---:|---:|---:|---|
| `AGENT_MODE` | runtime mode guardrail | ✅ | ✅ |  |  | Hard-fail if missing/invalid; allowed: `OFF`,`OBSERVE`,`EVAL`,`PAPER`; **`EXECUTE` hard-forbidden** |
| `TRADING_MODE` | repo-wide trading mode | ✅ | ✅ |  |  | Hard-fail unless `TRADING_MODE=paper` **AND APCA_API_BASE_URL contains `paper-api.alpaca.markets`** (paper-trading hard lock) |
| `ENV` | environment label |  |  | ✅ |  | Used for logs; also required by `cloudrun-consumer` contract |
| `ENVIRONMENT` | environment label alias |  |  | ✅ |  | Logging only (falls back chain includes `ENV`, `APP_ENV`, `DEPLOY_ENV`) |
| `APP_ENV` | environment label alias |  |  | ✅ |  | Logging only |
| `DEPLOY_ENV` | environment label alias |  |  | ✅ |  | Logging only |
| `SERVICE_NAME` | service name label |  |  | ✅ |  | Logging only (fallback chain includes `K_SERVICE`, `AGENT_NAME`) |
| `K_SERVICE` | Cloud Run service name |  |  | ✅ |  | Logging only; Cloud Run sets this automatically |
| `K_REVISION` | Cloud Run revision label |  |  | ✅ |  | Used in ops/status identity (`git_sha` fallback) |
| `GIT_SHA` | build git SHA |  |  | ✅ |  | Used for envelope + ops/status |
| `GITHUB_SHA` | build git SHA alias |  |  | ✅ |  | Used as fallback to `GIT_SHA` |
| `COMMIT_SHA` | build git SHA alias |  |  | ✅ |  | Used as fallback to `GIT_SHA` |
| `BUILD_ID` | build id label |  |  | ✅ |  | Used in ops/status |
| `LOG_LEVEL` | log verbosity |  |  | ✅ |  | Used widely (FastAPI + Cloud Run structured logs) |
| `PORT` | HTTP port |  | ✅ | ✅ |  | Used by `cloudrun-consumer` uvicorn main; Cloud Run sets `PORT` |
| `GOOGLE_APPLICATION_CREDENTIALS` | path to ADC JSON keyfile | ✅ (only if no ADC login) |  |  | ✅ | **Forbidden in prod**: prefer attached service account / ADC |
| `FIREBASE_PROJECT_ID` | Firebase/Firestore project id | ✅ (if Firestore used) | ✅ (recommended) |  |  | Preferred project id env; fallbacks exist but missing can hard-fail depending on ADC |
| `FIRESTORE_PROJECT_ID` | legacy Firestore project id |  |  | ✅ |  | Back-compat alias for `FIREBASE_PROJECT_ID` |
| `GOOGLE_CLOUD_PROJECT` | GCP project id (ADC default) |  |  | ✅ |  | Used as fallback for Firebase project resolution |
| `GCLOUD_PROJECT` | GCP project id alias |  |  | ✅ |  | Used as alias for `GCP_PROJECT` normalization |
| `GCP_PROJECT_ID` | GCP project id alias |  |  | ✅ |  | Used as alias for `GCP_PROJECT` normalization |
| `PROJECT_ID` | GCP project id alias |  |  | ✅ |  | Used as alias for `GCP_PROJECT` normalization |
| `PUBSUB_PROJECT_ID` | GCP project id alias (legacy) |  |  | ✅ |  | Included in contract alias set for `GCP_PROJECT` |
| `GCP_PROJECT` | canonical project id for Cloud Run ingestion/consumer | ✅ (for those services) | ✅ (for those services) |  |  | Required by `cloudrun-ingestor` and `cloudrun-consumer` contracts |
| `APCA_API_KEY_ID` | Alpaca key id | ✅ (if Alpaca used) | ✅ (if Alpaca used) |  |  | Canonical; required by `marketdata-mcp-server` contract |
| `APCA_API_SECRET_KEY` | Alpaca secret key | ✅ (if Alpaca used) | ✅ (if Alpaca used) |  |  | Canonical; required by `marketdata-mcp-server` contract |
| `APCA_API_BASE_URL` | Alpaca trading base url | ✅ (if Alpaca used) | ✅ (if Alpaca used) |  |  | Canonical; default is paper URL in some callers |
| `ALPACA_API_KEY` | Alpaca key alias |  |  | ✅ |  | Normalized to `APCA_API_KEY_ID` |
| `ALPACA_API_KEY_ID` | Alpaca key alias |  |  | ✅ |  | Normalized to `APCA_API_KEY_ID` |
| `ALPACA_SECRET_KEY` | Alpaca secret alias |  |  | ✅ |  | Normalized to `APCA_API_SECRET_KEY` |
| `ALPACA_API_SECRET_KEY` | Alpaca secret alias |  |  | ✅ |  | Normalized to `APCA_API_SECRET_KEY` |
| `ALPACA_TRADING_HOST` | Alpaca trading host alias |  |  | ✅ |  | Normalized to `APCA_API_BASE_URL` |
| `DATABASE_URL` | Postgres connection | ✅ (if service uses DB) | ✅ (if service uses DB) |  |  | Required by `marketdata-mcp-server` and `strategy-engine` contracts |
| `MARKETDATA_HEALTH_URL` | marketdata service health endpoint | ✅ (strategy-engine) | ✅ (strategy-engine) |  |  | `strategy-engine` requires `MARKETDATA_HEALTH_URL` OR `MARKETDATA_HEARTBEAT_URL` |
| `MARKETDATA_HEARTBEAT_URL` | marketdata heartbeat endpoint | ✅ (strategy-engine) | ✅ (strategy-engine) |  |  | Alternative to `MARKETDATA_HEALTH_URL` |
| `SYSTEM_EVENTS_TOPIC` | Pub/Sub topic name/path | ✅ (cloudrun services) | ✅ (cloudrun services) |  |  | Required by `cloudrun-ingestor` and `cloudrun-consumer` contracts |
| `MARKET_TICKS_TOPIC` | Pub/Sub topic name/path | ✅ (cloudrun-ingestor) | ✅ (cloudrun-ingestor) |  |  | Required by `cloudrun-ingestor` contract |
| `MARKET_BARS_1M_TOPIC` | Pub/Sub topic name/path | ✅ (cloudrun-ingestor) | ✅ (cloudrun-ingestor) |  |  | Required by `cloudrun-ingestor` contract |
| `TRADE_SIGNALS_TOPIC` | Pub/Sub topic name/path | ✅ (cloudrun-ingestor) | ✅ (cloudrun-ingestor) |  |  | Required by `cloudrun-ingestor` contract |
| `INGEST_FLAG_SECRET_ID` | Secret Manager id for ingest enable flag | ✅ (cloudrun services) | ✅ (cloudrun services) |  |  | Required by `cloudrun-ingestor` and `cloudrun-consumer` contracts |
| `HEARTBEAT_INTERVAL_SECONDS` | ingest heartbeat interval |  |  | ✅ |  | Optional for `cloudrun-ingestor` contract |
| `FLAG_CHECK_INTERVAL_SECONDS` | ingest flag poll interval |  |  | ✅ |  | Optional for `cloudrun-ingestor` contract |
| `INGEST_HEARTBEAT_SUBSCRIPTION_ID` | expected heartbeat subscription short id |  |  | ✅ |  | Used by `pubsub_event_ingestion_service`; default `ingest-heartbeat` |
| `LIVEZ_MAX_AGE_S` | liveness max loop age |  |  | ✅ |  | Used by market-ingest, strategy-service, consumer, pubsub-event-ingestion |
| `EVENT_STORE` | pubsub-event-ingestion store backend |  |  | ✅ |  | `EVENT_STORE=memory` forces in-memory store (visibility-first) |
| `DRY_RUN` | stream-bridge dry-run / Firestore write disable |  |  | ✅ |  | Used by `stream-bridge` and `FirestoreWriter.create_from_env()` |
| `FIRESTORE_DATABASE` | Firestore database id |  | ✅ (cloudrun-consumer) | ✅ |  | Optional; defaults to `(default)` |
| `FIRESTORE_COLLECTION_PREFIX` | prefix for Firestore collections |  |  | ✅ |  | Optional for `cloudrun-consumer` |
| `DEFAULT_REGION` | default region label |  |  | ✅ |  | Used by `cloudrun-consumer` |
| `SUBSCRIPTION_TOPIC_MAP` | subscription→topic mapping JSON/text |  |  | ✅ |  | Used by `cloudrun-consumer` |
| `FIRESTORE_RETRY_MAX_ATTEMPTS` | Firestore retry attempts |  |  | ✅ |  | `cloudrun-consumer` transient Firestore retry tuning |
| `FIRESTORE_RETRY_INITIAL_BACKOFF_S` | Firestore retry initial backoff |  |  | ✅ |  | `cloudrun-consumer` transient Firestore retry tuning |
| `FIRESTORE_RETRY_MAX_BACKOFF_S` | Firestore retry max backoff |  |  | ✅ |  | `cloudrun-consumer` transient Firestore retry tuning |
| `FIRESTORE_RETRY_MAX_TOTAL_S` | Firestore retry total cap |  |  | ✅ |  | `cloudrun-consumer` transient Firestore retry tuning |
| `DLQ_SAMPLE_RATE` | DLQ sampling fraction |  |  | ✅ |  | Optional for `cloudrun-consumer` contract |
| `DLQ_SAMPLE_TTL_HOURS` | DLQ marker TTL hours |  |  | ✅ |  | Optional for `cloudrun-consumer` contract |
| `REPLAY_RUN_ID` | replay marker grouping id |  |  | ✅ |  | Enables replay markers in `cloudrun-consumer` |
| `GUNICORN_CMD_ARGS` | runtime detection for Cloud Run worker |  |  | ✅ |  | Used by `cloudrun-ingestor` to detect “real runtime” (gunicorn) |
| `EXEC_DRY_RUN` | execution engine dry-run |  |  | ✅ |  | Defaults truthy (`"1"`). If `0`, broker placement is attempted (still paper-locked by `TRADING_MODE`) |
| `EXEC_AGENT_ID` | execution agent identity label |  |  | ✅ |  | Used for state machine id in execution service |
| `EXEC_SHUTDOWN_DRAIN_TIMEOUT_S` | drain timeout for shutdown |  |  | ✅ |  | Execution service shutdown behavior |
| `MARKETDATA_STALE_THRESHOLD_S` | marketdata heartbeat staleness |  |  | ✅ |  | Used by execution service ops/status + /state |
| `OPS_HEARTBEAT_TTL_S` | ops heartbeat TTL seconds |  |  | ✅ |  | Used by strategy engine + execution service |
| `OPS_HEARTBEAT_LOG_INTERVAL_S` | ops heartbeat log interval |  |  | ✅ |  | Used by stream-bridge, strategy-service, strategy-engine |
| `TENANT_ID` | tenant id fallback |  |  | ✅ |  | Used widely as fallback for tenant scoping |
| `EXEC_TENANT_ID` | execution tenant id |  |  | ✅ |  | Used by execution engine/service as preferred tenant id |
| `EXEC_UID` | execution uid fallback |  |  | ✅ |  | Used for risk gates and budget/capital reads when metadata is missing |
| `USER_ID` | uid alias |  |  | ✅ |  | Used in execution engine metadata fallback chain |
| `EXEC_CB_MAX_CONSECUTIVE_LOSSES` | per-strategy circuit breaker |  |  | ✅ |  | Optional; 0 disables |
| `EXECUTION_ENABLED` | global “execution enabled” toggle (strict in exec-agent gating) | ✅ (exec-agent) | ✅ (exec-agent) | ✅ (other) |  | For `execution-agent` startup gate: must be present AND exactly `"false"` |
| `EXECUTION_REPLICAS` | informational replicas count |  |  | ✅ |  | Ops/status only |
| `EXECUTION_HALTED` | kill switch (preferred) |  |  | ✅ |  | Truthy halts broker actions |
| `EXECUTION_HALTED_FILE` | kill switch via file contents |  |  | ✅ |  | Used for K8s ConfigMap mount patterns |
| `EXECUTION_HALTED_DOC` | legacy Firestore-backed halt doc path |  |  | ✅ |  | Checked by execution engine in addition to env/file switch |
| `EXEC_KILL_SWITCH` | deprecated kill switch alias |  |  | ✅ |  | Back-compat (deprecated) |
| `EXEC_KILL_SWITCH_FILE` | deprecated kill switch file alias |  |  | ✅ |  | Back-compat (deprecated) |
| `EXEC_KILL_SWITCH_DOC` | deprecated halt doc alias |  |  | ✅ |  | Back-compat (deprecated) |
| `EXEC_AGENT_ADMIN_KEY` | enables admin endpoints (/state, /recover auth) |  |  | ✅ |  | If set, callers must provide matching header; keep secret |
| `EXECUTION_CONFIRM_TOKEN` | live execution confirmation token |  |  | ✅ |  | **Future-only**: enforced only when live execution is enabled in code |
| `REPO_ID` | execution-agent strict gate | ✅ (exec-agent) | ✅ (exec-agent) |  |  | Must be exactly `agent-trader-v2` (case-sensitive) |
| `AGENT_NAME` | agent identity | ✅ (exec-agent) | ✅ (exec-agent) | ✅ |  | For exec-agent gate: must be exactly `execution-agent` |
| `AGENT_ROLE` | agent identity | ✅ (exec-agent) | ✅ (exec-agent) | ✅ |  | For exec-agent gate: must be exactly `execution` |
| `EXECUTION_AGENT_ENABLED` | exec-agent strict gate | ✅ (exec-agent) | ✅ (exec-agent) |  |  | Must be exactly `"true"` |
| `BROKER_EXECUTION_ENABLED` | exec-agent strict gate | ✅ (exec-agent) | ✅ (exec-agent) |  |  | Must be present AND exactly `"false"` |

> Note: Many additional non-contract env vars exist in other modules (strategy configs, stream tuning, etc.). This document intentionally focuses on the runtime contract surfaces requested above.

## Missing from docs/templates (gap list)

Compared against:
- `backend/.env.example`
- `infra/env.example.yaml`
- `infra/cloudrun/env/{execution_engine,market_ingest,backfill_bars}.env.yaml.example`
- `infra/cloudrun/services/*.service.yaml` templates (Cloud Run service specs)

### High-severity gaps (would crash containers)
- `TRADING_MODE` is **required** by `backend/common/agent_mode_guard.py` but was **missing** from:
  - `backend/.env.example` (now included)
  - all `infra/cloudrun/env/*.env.yaml.example` (now included)
  - `infra/cloudrun/services/*.service.yaml` templates (now included)
- Alpaca credentials were inconsistently documented as `ALPACA_*` in infra templates, but runtime canonical is `APCA_*`:
  - `infra/cloudrun/env/*.env.yaml.example` (now `APCA_*` + commented aliases)
  - `infra/cloudrun/services/{market-ingest,execution-engine}.service.yaml` (now `APCA_*` in comments)

### Coverage gaps (required for certain services, but no template exists)
- `cloudrun-ingestor` required vars have **no dedicated infra env template**:
  - `GCP_PROJECT`, `SYSTEM_EVENTS_TOPIC`, `MARKET_TICKS_TOPIC`, `MARKET_BARS_1M_TOPIC`, `TRADE_SIGNALS_TOPIC`, `INGEST_FLAG_SECRET_ID`

### Inconsistent canonical naming (docs/templates differ from code)
- `infra/env.example.yaml` uses `FIRESTORE_PROJECT_ID`, but repo canonical is `FIREBASE_PROJECT_ID` (with `FIRESTORE_PROJECT_ID` as back-compat).

## High-risk misconfiguration warnings (operator-facing)

- **Paper-trading hard lock is non-negotiable**: all runtime services that import `backend/common/agent_mode_guard.py` will **exit(13)** unless `TRADING_MODE=paper`. This is enforced even if other config contracts pass.
- **`AGENT_MODE=EXECUTE` is always forbidden**: will **exit(12)** immediately.
- **Do not use `GOOGLE_APPLICATION_CREDENTIALS` in production** (Cloud Run/GCE): it encourages keyfile deployment and increases blast radius. Prefer attached service account / ADC.
- **Execution-agent strict gate is fail-closed**: `backend/execution_agent/gating.py` requires exact string matches (case-sensitive) and will refuse to start if any are missing or mismatched (`BROKER_EXECUTION_ENABLED` and `EXECUTION_ENABLED` must be exactly `"false"`).
- **Mixed Alpaca env names can silently break auth**: set `APCA_*` canonically. Aliases are normalized, but relying on multiple names across deploy artifacts increases drift risk.

