#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "usage: $0 <gcp-project-id>" >&2
  exit 2
fi

echo "[ops] Dashboards:"
gcloud monitoring dashboards list --project="${PROJECT_ID}" --format="table(displayName,name)" || true

echo
echo "[ops] Alert policies:"
gcloud alpha monitoring policies list --project="${PROJECT_ID}" --format="table(displayName,name)" || true

echo
echo "[ops] Log-based metrics:"
gcloud logging metrics list --project="${PROJECT_ID}" --format="table(name,description)" || true

