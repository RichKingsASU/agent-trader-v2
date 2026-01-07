#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "usage: $0 <gcp-project-id>" >&2
  exit 2
fi

POLICY_DIR="ops/monitoring/alert_policies"

echo "[ops] Applying alert policies to project=${PROJECT_ID}"

apply_one() {
  local file="$1"
  local display_name="$2"

  local existing
  existing="$(gcloud alpha monitoring policies list --project="${PROJECT_ID}" \
    --filter="displayName=\"${display_name}\"" --format="value(name)" 2>/dev/null || true)"

  if [[ -n "${existing}" ]]; then
    echo "[ops] Updating policy: ${existing} (${display_name})"
    gcloud alpha monitoring policies update "${existing}" --project="${PROJECT_ID}" --policy-from-file="${file}"
  else
    echo "[ops] Creating policy: ${display_name}"
    gcloud alpha monitoring policies create --project="${PROJECT_ID}" --policy-from-file="${file}"
  fi
}

apply_one "${POLICY_DIR}/marketdata_stale_warning.json" "AgentTrader v2 — Marketdata stale (warning)"
apply_one "${POLICY_DIR}/strategy_engine_halted_critical.json" "AgentTrader v2 — Strategy engine halted/unhealthy (critical)"
apply_one "${POLICY_DIR}/crashloop_critical.json" "AgentTrader v2 — CrashLoop / frequent restarts (critical)"
apply_one "${POLICY_DIR}/error_rate_spike_warning.json" "AgentTrader v2 — Error rate spike (warning)"

echo "[ops] Done."

