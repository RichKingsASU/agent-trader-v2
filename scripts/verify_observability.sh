#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:-trading-floor}"

echo "[verify] namespace=${NAMESPACE}"

pycurl() {
  local pod="$1"
  local url="$2"
  kubectl -n "${NAMESPACE}" exec "${pod}" -- python -c "import urllib.request; print(urllib.request.urlopen('${url}', timeout=5).read().decode('utf-8'))"
}

pycurl_head() {
  local pod="$1"
  local url="$2"
  local n="${3:-800}"
  kubectl -n "${NAMESPACE}" exec "${pod}" -- python -c "import urllib.request; data=urllib.request.urlopen('${url}', timeout=5).read().decode('utf-8'); print(data[:${n}])"
}

require_metrics_present() {
  local pod="$1"
  local url="$2"
  URL="${url}" kubectl -n "${NAMESPACE}" exec "${pod}" -- python - <<'PY'
import os, sys, urllib.request
url = os.environ["URL"]
data = urllib.request.urlopen(url, timeout=5).read().decode("utf-8", errors="replace")
required = [
  "agent_start_total",
  "errors_total",
  "heartbeat_age_seconds",
  "marketdata_ticks_total",
  "marketdata_stale_total",
  "strategy_cycles_total",
  "strategy_cycles_skipped_total",
  "order_proposals_total",
  "safety_halted_total",
]
missing = [m for m in required if m not in data]
if missing:
  print("[verify] missing metrics:", missing)
  sys.exit(2)
print("[verify] required metrics present")
PY
}

echo
echo "[verify] marketdata-mcp-server endpoints"
MD_POD="$(kubectl -n "${NAMESPACE}" get pods -l app=marketdata-mcp-server -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [[ -z "${MD_POD}" ]]; then
  echo "[verify] WARN: no marketdata-mcp-server pod found"
else
  echo "[verify] pod=${MD_POD}"
  pycurl "${MD_POD}" "http://127.0.0.1:8080/ops/status"
  echo
  echo "[verify] /metrics (head)"
  pycurl_head "${MD_POD}" "http://127.0.0.1:8080/metrics" 1200
fi

echo
echo "[verify] strategy-engine endpoints (gamma/whale)"
for label in gamma whale; do
  POD="$(kubectl -n "${NAMESPACE}" get pods -l strategy="${label}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [[ -z "${POD}" ]]; then
    echo "[verify] INFO: no strategy=${label} pod found"
    continue
  fi
  echo "[verify] pod=${POD} strategy=${label}"
  pycurl "${POD}" "http://127.0.0.1:8080/ops/status" || true
  echo
  echo "[verify] /metrics (head)"
  pycurl_head "${POD}" "http://127.0.0.1:8080/metrics" 1200 || true
done

echo
echo "[verify] best-effort: list dashboards/alerts/log metrics (if gcloud configured)"
if command -v gcloud >/dev/null 2>&1; then
  if [[ -n "${MD_POD}" ]]; then
    # Validate required metrics on at least one pod (marketdata).
    require_metrics_present "${MD_POD}" "http://127.0.0.1:8080/metrics" || true
  fi
  echo
  echo "[verify] dashboards:"
  gcloud monitoring dashboards list --format="table(displayName,name)" 2>/dev/null || true
  echo
  echo "[verify] alert policies:"
  gcloud alpha monitoring policies list --format="table(displayName,name)" 2>/dev/null || true
else
  echo "[verify] INFO: gcloud not found; skipping monitoring resource listing"
fi

echo
echo "[verify] done"

