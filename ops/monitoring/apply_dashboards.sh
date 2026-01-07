#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "usage: $0 <gcp-project-id>" >&2
  exit 2
fi

DASH_FILE="ops/monitoring/dashboards/agenttrader_v2_ops_dashboard.json"
DISPLAY_NAME="AgentTrader v2 — Ops Overview (Golden Signals)"

echo "[ops] Applying dashboard to project=${PROJECT_ID}"

existing="$(gcloud monitoring dashboards list --project="${PROJECT_ID}" \
  --filter="displayName=\"${DISPLAY_NAME}\"" --format="value(name)" 2>/dev/null || true)"

if [[ -n "${existing}" ]]; then
  echo "[ops] Updating existing dashboard: ${existing}"
  gcloud monitoring dashboards update "${existing}" --project="${PROJECT_ID}" --config-from-file="${DASH_FILE}"
else
  echo "[ops] Creating dashboard from ${DASH_FILE}"
  gcloud monitoring dashboards create --project="${PROJECT_ID}" --config-from-file="${DASH_FILE}"
fi

echo "[ops] Done."

