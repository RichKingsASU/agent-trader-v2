#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=infra/cloudrun/common.sh
source "${ROOT_DIR}/infra/cloudrun/common.sh"

defaults
require_env PROJECT_ID
require_env RUN_SA_EMAIL

JOB_NAME="${JOB_NAME:-alpaca-bars-backfill}"
IMAGE_NAME="${IMAGE_NAME:-market-ingest}" # reuse ingest runtime image
DOCKERFILE="${DOCKERFILE:-${ROOT_DIR}/infra/Dockerfile.ingest}"
ENV_VARS_FILE="${ENV_VARS_FILE:-}"
SECRETS="${SECRETS:-}"          # e.g. 'ALPACA_API_KEY=alpaca-api-key:latest,ALPACA_SECRET_KEY=alpaca-secret-key:latest'
VPC_CONNECTOR="${VPC_CONNECTOR:-}"
VPC_EGRESS="${VPC_EGRESS:-all-traffic}" # all-traffic|private-ranges-only

artifact_repo_ensure "${PROJECT_ID}" "${REGION}" "${AR_REPO}"
IMAGE="$(image_ref "${PROJECT_ID}" "${REGION}" "${AR_REPO}" "${IMAGE_NAME}" "${IMAGE_TAG}")"

docker build -f "${DOCKERFILE}" -t "${IMAGE}" "${ROOT_DIR}"
docker push "${IMAGE}"

DEPLOY_ARGS=(
  run jobs deploy "${JOB_NAME}"
  --project "${PROJECT_ID}"
  --region "${REGION}"
  --image "${IMAGE}"
  --service-account "${RUN_SA_EMAIL}"
  --execution-environment gen2
  --max-retries 0
  --task-timeout 3600
  --command python
  --args "-m,backend.streams.alpaca_backfill_bars"
)

if [[ -n "${ENV_VARS_FILE}" ]]; then
  DEPLOY_ARGS+=(--env-vars-file "${ENV_VARS_FILE}")
fi
if [[ -n "${SECRETS}" ]]; then
  DEPLOY_ARGS+=(--set-secrets "${SECRETS}")
fi
if [[ -n "${VPC_CONNECTOR}" ]]; then
  DEPLOY_ARGS+=(--vpc-connector "${VPC_CONNECTOR}" --vpc-egress "${VPC_EGRESS}")
fi

gcloud "${DEPLOY_ARGS[@]}"

echo "Deployed job ${JOB_NAME} -> ${IMAGE}"

