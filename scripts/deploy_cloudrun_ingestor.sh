#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
deploy_cloudrun_ingestor.sh — build + deploy Cloud Run ingestor (Artifact Registry)

This script builds the `cloudrun_ingestor` container image, pushes it to Artifact
Registry, then deploys the Cloud Run service `agenttrader-ingestor` with a
runtime service account and required environment variables.

Safety/Idempotency:
- Safe to re-run: Artifact Registry repo creation and `gcloud run deploy` are idempotent.
- Uses explicit image tags (defaults to git short SHA; falls back to timestamp).
- Does not enable APIs or create IAM bindings (fails fast with actionable errors).

Required tools:
- gcloud, docker

Required configuration (set via env vars):
- SYSTEM_EVENTS_TOPIC        Pub/Sub topic name (NOT full path)
- MARKET_TICKS_TOPIC         Pub/Sub topic name (NOT full path)
- MARKET_BARS_1M_TOPIC       Pub/Sub topic name (NOT full path)
- TRADE_SIGNALS_TOPIC        Pub/Sub topic name (NOT full path)
- INGEST_FLAG_SECRET_ID      Secret Manager secret id for ingest kill-switch

Project/region resolution:
- PROJECT_ID: from $PROJECT_ID or `gcloud config get-value project`
- REGION: from $REGION or `gcloud config get-value run/region` (then compute/region, then zone→region)

Important env vars (optional overrides):
- SERVICE_NAME=agenttrader-ingestor
- RUN_SA_EMAIL=agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com
- AR_REPO=agenttrader
- IMAGE_NAME=agenttrader-ingestor
- IMAGE_TAG=<tag>                      (default: git short SHA, else timestamp)
- DOCKERFILE=<path>                    (default: cloudrun_ingestor/Dockerfile)
- ENV=prod                             (default: prod)
- LOG_LEVEL=INFO                       (optional)
- CPU=1, MEMORY=512Mi, TIMEOUT=3600, CONCURRENCY=1, MIN_INSTANCES=1, MAX_INSTANCES=1
- VPC_CONNECTOR=<name>                 (optional)
- VPC_EGRESS=private-ranges-only|all-traffic (default: private-ranges-only)
- SECRETS='<ENV_NAME>=<SECRET>:<VERSION>,...' (optional, passed to `--set-secrets`)

Example invocation:
  SYSTEM_EVENTS_TOPIC="system-events" \
  MARKET_TICKS_TOPIC="market-ticks" \
  MARKET_BARS_1M_TOPIC="market-bars-1m" \
  TRADE_SIGNALS_TOPIC="trade-signals" \
  INGEST_FLAG_SECRET_ID="ingest-enabled" \
  RUN_SA_EMAIL="agenttrader-run@$(gcloud config get-value project).iam.gserviceaccount.com" \
  ./scripts/deploy_cloudrun_ingestor.sh

EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    die "Missing required env var: ${name}"
  fi
}

trim() {
  # shellcheck disable=SC2001
  echo "$1" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

gcloud_cfg() {
  # Returns empty string on unset / error.
  local key="$1"
  gcloud config get-value "${key}" 2>/dev/null \
    | tr -d '\r' \
    | awk 'NF && $0 != "(unset)" {print; exit}' \
    || true
}

zone_to_region() {
  # us-central1-a -> us-central1
  local zone="$1"
  zone="$(trim "${zone}")"
  if [[ "${zone}" == *"-"*"-"* ]]; then
    echo "${zone%-*}"
    return 0
  fi
  echo ""
}

resolve_project_and_region() {
  if [[ -z "${PROJECT_ID:-}" ]]; then
    PROJECT_ID="$(gcloud_cfg project)"
  fi
  PROJECT_ID="$(trim "${PROJECT_ID:-}")"
  [[ -n "${PROJECT_ID}" ]] || die "PROJECT_ID not set and no gcloud default project configured"

  if [[ -z "${REGION:-}" ]]; then
    REGION="$(gcloud_cfg run/region)"
  fi
  if [[ -z "${REGION:-}" ]]; then
    REGION="$(gcloud_cfg compute/region)"
  fi
  if [[ -z "${REGION:-}" ]]; then
    local zone
    zone="$(gcloud_cfg compute/zone)"
    REGION="$(zone_to_region "${zone}")"
  fi
  if [[ -z "${REGION:-}" ]]; then
    REGION="us-central1"
    echo "WARN: REGION not set and not found in gcloud config; defaulting to ${REGION}" >&2
  fi
  REGION="$(trim "${REGION}")"
}

artifact_repo_ensure() {
  local project_id="$1"
  local region="$2"
  local repo="$3"

  if gcloud artifacts repositories describe "${repo}" --location "${region}" --project "${project_id}" >/dev/null 2>&1; then
    return 0
  fi

  gcloud artifacts repositories create "${repo}" \
    --repository-format docker \
    --location "${region}" \
    --project "${project_id}" \
    --description "AgentTrader Cloud Run images" >/dev/null
}

image_ref() {
  local project_id="$1"
  local region="$2"
  local repo="$3"
  local image_name="$4"
  local tag="$5"
  echo "${region}-docker.pkg.dev/${project_id}/${repo}/${image_name}:${tag}"
}

join_by_comma() {
  local out=""
  local s
  for s in "$@"; do
    if [[ -z "${out}" ]]; then
      out="${s}"
    else
      out="${out},${s}"
    fi
  done
  echo "${out}"
}

main() {
  require_cmd gcloud
  require_cmd docker

  local root_dir
  root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

  resolve_project_and_region

  export SERVICE_NAME="${SERVICE_NAME:-agenttrader-ingestor}"
  export AR_REPO="${AR_REPO:-agenttrader}"
  export IMAGE_NAME="${IMAGE_NAME:-agenttrader-ingestor}"
  export DOCKERFILE="${DOCKERFILE:-${root_dir}/cloudrun_ingestor/Dockerfile}"

  # Prefer git short SHA if available; fall back to timestamp.
  local git_sha
  git_sha="$(git -C "${root_dir}" rev-parse --short HEAD 2>/dev/null || true)"
  export IMAGE_TAG="${IMAGE_TAG:-${GIT_SHA:-${git_sha:-$(date +%Y%m%d-%H%M%S)}}}"

  export RUN_SA_EMAIL="${RUN_SA_EMAIL:-agenttrader-run@${PROJECT_ID}.iam.gserviceaccount.com}"

  export CPU="${CPU:-1}"
  export MEMORY="${MEMORY:-512Mi}"
  export TIMEOUT="${TIMEOUT:-3600}"
  export CONCURRENCY="${CONCURRENCY:-1}"
  export MIN_INSTANCES="${MIN_INSTANCES:-1}"
  export MAX_INSTANCES="${MAX_INSTANCES:-1}"
  export VPC_CONNECTOR="${VPC_CONNECTOR:-}"
  export VPC_EGRESS="${VPC_EGRESS:-private-ranges-only}"
  export SECRETS="${SECRETS:-}"

  export ENV="${ENV:-prod}"

  require_env SYSTEM_EVENTS_TOPIC
  require_env MARKET_TICKS_TOPIC
  require_env MARKET_BARS_1M_TOPIC
  require_env TRADE_SIGNALS_TOPIC
  require_env INGEST_FLAG_SECRET_ID

  # Fail fast if the runtime service account doesn't exist (common misconfig).
  gcloud iam service-accounts describe "${RUN_SA_EMAIL}" --project "${PROJECT_ID}" >/dev/null 2>&1 || \
    die "Runtime service account not found: ${RUN_SA_EMAIL} (create it and grant required roles; see docs/DEPLOY_GCP.md)"

  artifact_repo_ensure "${PROJECT_ID}" "${REGION}" "${AR_REPO}"

  # Ensure Docker can push to Artifact Registry in this region (idempotent).
  gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet >/dev/null

  local image
  image="$(image_ref "${PROJECT_ID}" "${REGION}" "${AR_REPO}" "${IMAGE_NAME}" "${IMAGE_TAG}")"

  docker build -f "${DOCKERFILE}" -t "${image}" "${root_dir}"
  docker push "${image}"

  local env_pairs=(
    "GIT_SHA=${IMAGE_TAG}"
    "ENV=${ENV}"
    "GCP_PROJECT=${PROJECT_ID}"
    "SYSTEM_EVENTS_TOPIC=${SYSTEM_EVENTS_TOPIC}"
    "MARKET_TICKS_TOPIC=${MARKET_TICKS_TOPIC}"
    "MARKET_BARS_1M_TOPIC=${MARKET_BARS_1M_TOPIC}"
    "TRADE_SIGNALS_TOPIC=${TRADE_SIGNALS_TOPIC}"
    "INGEST_FLAG_SECRET_ID=${INGEST_FLAG_SECRET_ID}"
  )
  if [[ -n "${LOG_LEVEL:-}" ]]; then
    env_pairs+=("LOG_LEVEL=${LOG_LEVEL}")
  fi

  local env_csv
  env_csv="$(join_by_comma "${env_pairs[@]}")"

  local deploy_args=(
    run deploy "${SERVICE_NAME}"
    --project "${PROJECT_ID}"
    --region "${REGION}"
    --image "${image}"
    --service-account "${RUN_SA_EMAIL}"
    --execution-environment gen2
    --no-allow-unauthenticated
    --cpu "${CPU}"
    --memory "${MEMORY}"
    --timeout "${TIMEOUT}"
    --concurrency "${CONCURRENCY}"
    --min-instances "${MIN_INSTANCES}"
    --max-instances "${MAX_INSTANCES}"
    --set-env-vars "${env_csv}"
  )

  if [[ -n "${SECRETS}" ]]; then
    deploy_args+=(--set-secrets "${SECRETS}")
  fi
  if [[ -n "${VPC_CONNECTOR}" ]]; then
    deploy_args+=(--vpc-connector "${VPC_CONNECTOR}" --vpc-egress "${VPC_EGRESS}")
  fi

  gcloud "${deploy_args[@]}"

  echo "Deployed ${SERVICE_NAME} -> ${image}"
}

main "$@"

