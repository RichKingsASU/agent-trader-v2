## Deployment (Cloud Run)

This repo supports multiple **production deployment surfaces** (each with explicit safety posture):

- **Cloud Run (GCP)**: market ingestion + execution engine (authoritative: `docs/DEPLOY_GCP.md`)
- **Kubernetes (GKE)**: “trading floor” workloads pinned to digests (see `k8s/` and `ops/PRODUCTION_LOCK.md`)
- **Firebase Hosting**: Ops Dashboard UI (authoritative: `docs/ops/firebase_ops_dashboard_deploy.md`)

### Safety posture (non-negotiable)

- **Default is non-executing / observe-only**. Do not enable trading execution as part of deploy/ops work.
- **Kill switch must remain HALTED by default**: `EXECUTION_HALTED=1` (see `docs/KILL_SWITCH.md`).
- **Ingestion has a separate pause switch** (`INGEST_ENABLED`) for stopping the blast radius without redeploying (see `docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md`).

### Build locally (ingestion)

```bash
docker build -f infra/Dockerfile.ingest -t agenttrader-ingest:local .
```

### Run locally (ingestion)

The ingestion container defaults to running `backend.ingestion.market_data_ingest`.

Example “boot test” run (no secrets; short-lived):

```bash
docker run --rm \
  -e DRY_RUN=1 \
  -e STOP_AFTER_SECONDS=2 \
  agenttrader-ingest:local
```

### Cloud Build (build images)

These Cloud Build configs build container images (Docker build).

- Ingestion: `infra/cloudbuild_ingest.yaml`
- Strategy engine: `infra/cloudbuild_strategy_engine.yaml`
- Stream bridge: `infra/cloudbuild_stream_bridge.yaml`
- Options ingest: `infra/cloudbuild_options_ingest.yaml`

Note: the production Cloud Run deploy path is documented in `docs/DEPLOY_GCP.md` and uses scripts under `infra/cloudrun/`.

### Cloud Run Jobs (deploy ingestion)

Recommended env var file template: `infra/env.example.yaml` (names only).

Create/update the job (image-based deploy):

```bash
JOB_NAME="agenttrader-market-ingest"
REGION="us-central1"
IMAGE="gcr.io/PROJECT_ID/agenttrader-alpaca-ingest"

gcloud run jobs deploy "${JOB_NAME}" \
  --image "${IMAGE}" \
  --region "${REGION}" \
  --env-vars-file "PATH_TO_ENV_VARS_FILE" \
  --set-secrets "APCA_API_KEY_ID=SECRET_NAME:latest,APCA_API_SECRET_KEY=SECRET_NAME:latest,APCA_API_BASE_URL=SECRET_NAME:latest"
```

Required env vars (names only):

- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`
- `APCA_API_BASE_URL`
- `ALPACA_SYMBOLS`
- `ALPACA_DATA_FEED`
- `FIRESTORE_PROJECT_ID`

Run the job:

```bash
gcloud run jobs execute "${JOB_NAME}" --region "${REGION}" --wait
```

---

## Rollback

Rollback is documented in `docs/ops/rollback.md` and follows a “return to last-known-good” posture:

- **Kubernetes**: restore to `ops/lkg/` (safe-by-default; forces `EXECUTION_HALTED=1`)
- **Cloud Run**: shift traffic back to a prior revision (services) or redeploy a prior digest (jobs)
- **Ops Dashboard (Firebase Hosting)**: redeploy the last-known-good commit/release (no emergency edits)

## Runbooks (paper vs live)

- **Paper / observe-only operations**: `docs/ops/runbooks/paper_trading.md`
- **Live trading operations (controlled unlock only)**: `docs/ops/runbooks/live_trading.md`

## Incident response notes

See `docs/ops/incident_response.md` (links to the relevant runbooks and evidence artifacts).
