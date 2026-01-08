# Deploy to GCP (Cloud Run) — production path

This repo is designed to run on **Cloud Run with runtime Application Default Credentials (ADC)**:

- **No service account JSON keys**
- **No secrets committed to the repo**
- Runtime access is controlled by the **Cloud Run service account** attached to each service/job

Deployer note: the scripts under `infra/cloudrun/` use **local Docker build + push** to Artifact Registry and then `gcloud run deploy`.

---

## What gets deployed

- **Market ingestion service**: `market-ingest`
  - Container runs a small HTTP server for health checks and runs the websocket ingest loop in the background.
- **Execution engine service**: `execution-engine`
  - HTTP API wrapper around `backend.execution.engine.ExecutionEngine`
- **Optional backfill job**: `alpaca-bars-backfill`
  - Cloud Run Job running `python -m backend.streams.alpaca_backfill_bars`
- **Optional scheduler**: Cloud Scheduler triggers the backfill job via the Cloud Run Jobs API

---

## One-time GCP project setup

Set these in your shell:

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"
```

Enable required APIs:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project "${PROJECT_ID}"
```

If you will use the optional scheduler:

```bash
gcloud services enable cloudscheduler.googleapis.com --project "${PROJECT_ID}"
```

---

## Runtime identity (service accounts + Firestore)

Create a runtime service account (example: one SA shared by both services/jobs):

```bash
gcloud iam service-accounts create agenttrader-run \
  --project "${PROJECT_ID}" \
  --display-name "AgentTrader Cloud Run runtime"
```

Attach **Firestore permissions** (this satisfies “Cloud Run service account has Firestore permissions”):

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role "roles/datastore.user"
```

Notes:

- Firestore IAM roles are under **Datastore** (e.g. `roles/datastore.user`).
- If you need read-only, use `roles/datastore.viewer` instead.

---

## Deployer IAM (who runs the deploy scripts)

The identity running deploy needs (typical):

- **Cloud Run deploy**: `roles/run.admin`
- **Impersonate runtime SA during deploy**: `roles/iam.serviceAccountUser` on the runtime SA
- **Push images**: `roles/artifactregistry.writer`

Example (grant project-level roles to a human user):

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "user:YOU@YOURDOMAIN.COM" \
  --role "roles/run.admin"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "user:YOU@YOURDOMAIN.COM" \
  --role "roles/artifactregistry.writer"

gcloud iam service-accounts add-iam-policy-binding \
  "agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member "user:YOU@YOURDOMAIN.COM" \
  --role "roles/iam.serviceAccountUser" \
  --project "${PROJECT_ID}"
```

---

## Secrets (recommended: Secret Manager)

This repo intentionally does **not** store secrets. Recommended pattern:

1) Store sensitive values in Secret Manager:

```bash
# Example names only; do not paste secrets in shell history in shared terminals.
gcloud secrets create alpaca-api-key --replication-policy=automatic --project "${PROJECT_ID}"
gcloud secrets create alpaca-secret-key --replication-policy=automatic --project "${PROJECT_ID}"
```

2) Grant the runtime service account access to the secrets:

```bash
gcloud secrets add-iam-policy-binding alpaca-api-key \
  --member "serviceAccount:agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role "roles/secretmanager.secretAccessor" \
  --project "${PROJECT_ID}"

gcloud secrets add-iam-policy-binding alpaca-secret-key \
  --member "serviceAccount:agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role "roles/secretmanager.secretAccessor" \
  --project "${PROJECT_ID}"
```

If you use Secret Manager with the deploy scripts, pass:

- `SECRETS='APCA_API_KEY_ID=alpaca-api-key:latest,APCA_API_SECRET_KEY=alpaca-secret-key:latest'`

---

## Deploy: market ingestion service

Required env var **names** are listed in:

- `infra/cloudrun/env/market_ingest.env.yaml.example`

Create a local env-vars file (untracked) and fill values:

```bash
cp infra/cloudrun/env/market_ingest.env.yaml.example ./market_ingest.env.yaml
```

Deploy:

```bash
export RUN_SA_EMAIL="agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com"

# Option A: plain env vars (local file, not committed)
ENV_VARS_FILE=./market_ingest.env.yaml \
  ./infra/cloudrun/deploy_market_ingest.sh

# Option B: Secret Manager for Alpaca keys (recommended)
SECRETS='APCA_API_KEY_ID=alpaca-api-key:latest,APCA_API_SECRET_KEY=alpaca-secret-key:latest' \
  ENV_VARS_FILE=./market_ingest.env.yaml \
  ./infra/cloudrun/deploy_market_ingest.sh
```

---

## Deploy: execution engine service

Required env var **names** are listed in:

- `infra/cloudrun/env/execution_engine.env.yaml.example`

Create a local env-vars file (untracked):

```bash
cp infra/cloudrun/env/execution_engine.env.yaml.example ./execution_engine.env.yaml
```

Deploy:

```bash
export RUN_SA_EMAIL="agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com"

ENV_VARS_FILE=./execution_engine.env.yaml \
  ./infra/cloudrun/deploy_execution_engine.sh
```

By default, the deploy script sets **no public access** (`--no-allow-unauthenticated`).
To allow public access (not recommended for trading), set:

```bash
ALLOW_UNAUTHENTICATED=1 ENV_VARS_FILE=./execution_engine.env.yaml ./infra/cloudrun/deploy_execution_engine.sh
```

---

## Optional: backfill job + scheduler

### Deploy the job

Env var **names** are listed in:

- `infra/cloudrun/env/backfill_bars.env.yaml.example`

Create a local env-vars file (untracked):

```bash
cp infra/cloudrun/env/backfill_bars.env.yaml.example ./backfill_bars.env.yaml
```

Deploy the job:

```bash
export RUN_SA_EMAIL="agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com"

ENV_VARS_FILE=./backfill_bars.env.yaml \
  ./infra/cloudrun/deploy_backfill_job.sh
```

Run it manually:

```bash
gcloud run jobs execute alpaca-bars-backfill --region "${REGION}" --project "${PROJECT_ID}"
```

### Schedule it (Cloud Scheduler)

Create a scheduler service account (separate from runtime is recommended):

```bash
gcloud iam service-accounts create agenttrader-scheduler \
  --project "${PROJECT_ID}" \
  --display-name "AgentTrader Cloud Scheduler caller"
```

Grant permissions needed to trigger the Cloud Run Jobs API:

```bash
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "serviceAccount:agenttrader-scheduler@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role "roles/run.developer"
```

Allow Cloud Scheduler to mint OAuth tokens as that service account:

```bash
PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"

gcloud iam service-accounts add-iam-policy-binding \
  "agenttrader-scheduler@${PROJECT_ID}.iam.gserviceaccount.com" \
  --member "serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-cloudscheduler.iam.gserviceaccount.com" \
  --role "roles/iam.serviceAccountTokenCreator" \
  --project "${PROJECT_ID}"
```

Create/update the scheduler:

```bash
export SCHEDULER_SA_EMAIL="agenttrader-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

# Defaults to 02:00 UTC daily; override with SCHEDULE_CRON / TIME_ZONE if needed
./infra/cloudrun/create_backfill_scheduler.sh
```

---

## Logging & monitoring basics

- **Logs**: Cloud Run writes stdout/stderr to Cloud Logging automatically.
  - Read logs:
    - `gcloud run services logs read market-ingest --region "${REGION}" --project "${PROJECT_ID}"`
    - `gcloud run services logs read execution-engine --region "${REGION}" --project "${PROJECT_ID}"`
- **Health checks**:
  - `market-ingest` exposes `GET /health`
  - `execution-engine` exposes `GET /health`
- **Metrics**: start with the Cloud Run dashboards in Cloud Console:
  - request count / latency (execution-engine)
  - container restarts and instance uptime (market-ingest)

---

## Kubernetes: automated deployment health report (optional)

If you deploy any components on Kubernetes (e.g., via the manifests under `k8s/`), you can generate a single markdown deployment report (pods, deployments, rollouts, images, warning events).

See `docs/DEPLOYMENT_REPORT.md`.

