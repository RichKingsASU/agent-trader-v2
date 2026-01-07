#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=infra/cloudrun/common.sh
source "${ROOT_DIR}/infra/cloudrun/common.sh"

defaults
require_env PROJECT_ID
require_env RUN_SA_EMAIL

SERVICE_NAME="${SERVICE_NAME:-execution-engine}"
IMAGE_NAME="${IMAGE_NAME:-execution-engine}"
DOCKERFILE="${DOCKERFILE:-${ROOT_DIR}/infra/Dockerfile.execution_engine}"
ENV_VARS_FILE="${ENV_VARS_FILE:-}"
SECRETS="${SECRETS:-}"          # e.g. 'ALPACA_API_KEY=alpaca-api-key:latest,ALPACA_SECRET_KEY=alpaca-secret-key:latest'
VPC_CONNECTOR="${VPC_CONNECTOR:-}"
VPC_EGRESS="${VPC_EGRESS:-private-ranges-only}" # all-traffic|private-ranges-only
ALLOW_UNAUTHENTICATED="${ALLOW_UNAUTHENTICATED:-0}"

artifact_repo_ensure "${PROJECT_ID}" "${REGION}" "${AR_REPO}"
IMAGE="$(image_ref "${PROJECT_ID}" "${REGION}" "${AR_REPO}" "${IMAGE_NAME}" "${IMAGE_TAG}")"

docker build -f "${DOCKERFILE}" -t "${IMAGE}" "${ROOT_DIR}"
docker push "${IMAGE}"

EFFECTIVE_GIT_SHA="${GIT_SHA:-${IMAGE_TAG}}"

DEPLOY_ARGS=(
  run deploy "${SERVICE_NAME}"
  --project "${PROJECT_ID}"
  --region "${REGION}"
  --image "${IMAGE}"
  --service-account "${RUN_SA_EMAIL}"
  --execution-environment gen2
  --cpu 1
  --memory 512Mi
  --timeout 60
  --concurrency 10
  --min-instances 0
  --max-instances 10
)
DEPLOY_ARGS+=(--set-env-vars "GIT_SHA=${EFFECTIVE_GIT_SHA}")

if [[ "${ALLOW_UNAUTHENTICATED}" == "1" ]]; then
  DEPLOY_ARGS+=(--allow-unauthenticated)
else
  DEPLOY_ARGS+=(--no-allow-unauthenticated)
fi

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

echo "Deployed ${SERVICE_NAME} -> ${IMAGE}"

