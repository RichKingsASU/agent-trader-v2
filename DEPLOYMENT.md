## Deployment (Cloud Run)

This repo supports a **multi-container** deployment model:

- **Backend API service**: `Dockerfile`
- **Ingestion job (canonical)**: `infra/Dockerfile.ingest` (runs `python -m backend.ingestion.market_data_ingest`)
- **Other deployable containers (optional)**:
  - Strategy engine: `infra/Dockerfile.strategy_engine`
  - Stream bridge: `infra/Dockerfile.stream_bridge`
  - Options ingest: `infra/Dockerfile.options_ingest`

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

Example:

```bash
gcloud builds submit --config infra/cloudbuild_ingest.yaml .
```

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

