#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=infra/cloudrun/common.sh
source "${ROOT_DIR}/infra/cloudrun/common.sh"

defaults
require_env PROJECT_ID

# Cloud Scheduler runs in a location (region). Keep it aligned with Cloud Run region by default.
SCHEDULER_LOCATION="${SCHEDULER_LOCATION:-${REGION}}"

JOB_NAME="${JOB_NAME:-alpaca-bars-backfill}"
SCHEDULER_NAME="${SCHEDULER_NAME:-alpaca-bars-backfill-schedule}"
SCHEDULE_CRON="${SCHEDULE_CRON:-0 2 * * *}" # daily at 02:00
TIME_ZONE="${TIME_ZONE:-Etc/UTC}"

# Service account used by Cloud Scheduler to call the Cloud Run Jobs API.
require_env SCHEDULER_SA_EMAIL

# Cloud Run Jobs v2 API endpoint.
RUN_API_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

create_or_update() {
  if gcloud scheduler jobs describe "${SCHEDULER_NAME}" --location "${SCHEDULER_LOCATION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "${SCHEDULER_NAME}" \
      --location "${SCHEDULER_LOCATION}" \
      --project "${PROJECT_ID}" \
      --schedule "${SCHEDULE_CRON}" \
      --time-zone "${TIME_ZONE}" \
      --uri "${RUN_API_URI}" \
      --http-method POST \
      --oauth-service-account-email "${SCHEDULER_SA_EMAIL}" \
      --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
      --message-body "{}"
  else
    gcloud scheduler jobs create http "${SCHEDULER_NAME}" \
      --location "${SCHEDULER_LOCATION}" \
      --project "${PROJECT_ID}" \
      --schedule "${SCHEDULE_CRON}" \
      --time-zone "${TIME_ZONE}" \
      --uri "${RUN_API_URI}" \
      --http-method POST \
      --oauth-service-account-email "${SCHEDULER_SA_EMAIL}" \
      --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
      --message-body "{}"
  fi
}

create_or_update

echo "Scheduled ${JOB_NAME} via ${SCHEDULER_NAME} (${SCHEDULE_CRON} ${TIME_ZONE})"

