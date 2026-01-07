#!/usr/bin/env bash
set -euo pipefail

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    die "Missing required env var: ${name}"
  fi
}

defaults() {
  export PROJECT_ID="${PROJECT_ID:-}"
  export REGION="${REGION:-us-central1}"
  export AR_REPO="${AR_REPO:-agenttrader}"
  # Prefer an explicit git sha if provided by CI.
  export IMAGE_TAG="${IMAGE_TAG:-${GIT_SHA:-$(date +%Y%m%d-%H%M%S)}}"
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
    --description "AgentTrader Cloud Run images"
}

image_ref() {
  local project_id="$1"
  local region="$2"
  local repo="$3"
  local image_name="$4"
  local tag="$5"
  echo "${region}-docker.pkg.dev/${project_id}/${repo}/${image_name}:${tag}"
}

