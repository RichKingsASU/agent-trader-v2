#!/usr/bin/env bash
set -euo pipefail

# One-command end-to-end data plane smoke test:
#   ingestor (publisher) -> Pub/Sub -> consumer -> Firestore
#
# CI/local usage:
#   ./scripts/data_plane_smoke_test.sh
#
# Staging usage (real env; assumes infra exists):
#   SMOKE_MODE=staging GCP_PROJECT=... SYSTEM_EVENTS_TOPIC=system-events \
#     SMOKE_ASSERT_CLOUD_LOGGING=1 ./scripts/data_plane_smoke_test.sh

MODE="${SMOKE_MODE:-ci}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

PY="${PYTHON:-python3}"

if [[ "${MODE}" == "staging" ]]; then
  exec "${PY}" scripts/data_plane_smoke_test.py --mode staging "$@"
fi

# --- CI/local emulator mode ---
if ! command -v docker >/dev/null 2>&1; then
  # Allow running in environments where emulators are already available (or docker is disallowed).
  if [[ -n "${PUBSUB_EMULATOR_HOST:-}" && -n "${FIRESTORE_EMULATOR_HOST:-}" ]]; then
    exec "${PY}" scripts/data_plane_smoke_test.py --mode ci "$@"
  fi
  echo "ERROR: docker is required for CI smoke test (or set PUBSUB_EMULATOR_HOST + FIRESTORE_EMULATOR_HOST)" >&2
  exit 1
fi

PUBSUB_PORT="${PUBSUB_EMULATOR_PORT:-8085}"
FIRESTORE_PORT="${FIRESTORE_EMULATOR_PORT:-8080}"
PROJECT_ID="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-smoke-test}}"

export SMOKE_MODE="ci"
export GCP_PROJECT="${PROJECT_ID}"
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export GCLOUD_PROJECT="${PROJECT_ID}"

export SYSTEM_EVENTS_TOPIC="${SYSTEM_EVENTS_TOPIC:-system-events}"
export ENV="${ENV:-ci}"
export DEFAULT_REGION="${DEFAULT_REGION:-us-central1}"
export INGEST_FLAG_SECRET_ID="${INGEST_FLAG_SECRET_ID:-dummy}"

export PUBSUB_EMULATOR_HOST="127.0.0.1:${PUBSUB_PORT}"
export FIRESTORE_EMULATOR_HOST="127.0.0.1:${FIRESTORE_PORT}"

IMG="${SMOKE_EMULATORS_IMAGE:-gcr.io/google.com/cloudsdktool/cloud-sdk:emulators}"

PUBSUB_CID=""
FIRESTORE_CID=""

cleanup() {
  if [[ -n "${PUBSUB_CID}" ]]; then docker rm -f "${PUBSUB_CID}" >/dev/null 2>&1 || true; fi
  if [[ -n "${FIRESTORE_CID}" ]]; then docker rm -f "${FIRESTORE_CID}" >/dev/null 2>&1 || true; fi
}
trap cleanup EXIT

echo "Starting Pub/Sub emulator on ${PUBSUB_EMULATOR_HOST}..."
PUBSUB_CID="$(docker run -d --rm --network host "${IMG}" bash -lc \
  "gcloud beta emulators pubsub start --host-port=127.0.0.1:${PUBSUB_PORT} --quiet")"

echo "Starting Firestore emulator on ${FIRESTORE_EMULATOR_HOST}..."
FIRESTORE_CID="$(docker run -d --rm --network host "${IMG}" bash -lc \
  "gcloud beta emulators firestore start --host-port=127.0.0.1:${FIRESTORE_PORT} --quiet")"

echo "Waiting for emulators to accept connections..."
sleep 3

# Install lightweight deps needed for consumer + pubsub/firestore clients.
# (CI already installs most backend deps; keep this idempotent.)
${PY} -m pip install -q --upgrade pip >/dev/null
${PY} -m pip install -q -r cloudrun_consumer/requirements.txt -r backend/ingestion/requirements.txt >/dev/null

exec "${PY}" scripts/data_plane_smoke_test.py --mode ci "$@"

