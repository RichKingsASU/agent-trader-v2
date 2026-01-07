#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${1:-}"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "usage: $0 <gcp-project-id>" >&2
  exit 2
fi

DIR="ops/monitoring/log_based_metrics"

echo "[ops] Applying log-based metrics to project=${PROJECT_ID}"

apply_one() {
  local name="$1"
  local cfg="$2"

  if gcloud logging metrics describe "${name}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
    echo "[ops] Updating logging metric: ${name}"
    gcloud logging metrics update "${name}" --project="${PROJECT_ID}" --config-from-file="${cfg}"
  else
    echo "[ops] Creating logging metric: ${name}"
    gcloud logging metrics create "${name}" --project="${PROJECT_ID}" --config-from-file="${cfg}"
  fi
}

apply_one "agenttrader_strategy_cycle_skipped_count" "${DIR}/strategy_cycle_skipped.json"
apply_one "agenttrader_order_proposal_count" "${DIR}/order_proposal.json"
apply_one "agenttrader_marketdata_stale_reason_count" "${DIR}/marketdata_stale_reason.json"

echo "[ops] Done."

