#!/usr/bin/env bash
set -euo pipefail

# Safe, read-only status snapshot for AgentTrader v2.
#
# - Shows common workload types in a namespace
# - Best-effort /ops/status probe to Mission Control (does not fail status if curl fails)
# - Supports optional --context for deterministic cluster targeting

NS="default"
CTX=""
MISSION_CONTROL_URL="http://agenttrader-mission-control"

usage() {
  cat <<'EOF'
Usage: ./scripts/kubectl_status.sh [--namespace <ns>] [--context <ctx>] [--mission-control-url <url>]

Examples:
  ./scripts/kubectl_status.sh --namespace trading-floor
  ./scripts/kubectl_status.sh --namespace trading-floor --context gke_proj_region_cluster
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n) NS="${2:?}"; shift 2;;
    --context) CTX="${2:?}"; shift 2;;
    --mission-control-url) MISSION_CONTROL_URL="${2:?}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: unknown arg: $1" >&2; usage; exit 2;;
  esac
done

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not found. Install kubectl or run in an environment that provides it." >&2
  exit 2
fi

kargs=()
if [[ -n "${CTX}" ]]; then
  kargs+=(--context "${CTX}")
fi

echo "== kubectl status =="
echo "namespace: ${NS}"
echo "context:   $(kubectl "${kargs[@]}" config current-context 2>/dev/null || echo "UNKNOWN")"
echo ""

set +e
kubectl "${kargs[@]}" get namespace "${NS}" >/dev/null 2>&1
ns_ok=$?
set -e
if [[ "${ns_ok}" != "0" ]]; then
  echo "ERROR: cluster unreachable or namespace '${NS}' not found." >&2
  echo "HINT: verify context (kubectl config get-contexts) and namespace (kubectl get ns)." >&2
  exit 1
fi

echo "== workloads (deploy,sts,svc) =="
kubectl "${kargs[@]}" -n "${NS}" get deploy,sts,svc -o wide || true
echo ""

echo "== pods (top-level signal) =="
kubectl "${kargs[@]}" -n "${NS}" get pods -o wide || true
echo ""

echo "== recent events (last 25) =="
kubectl "${kargs[@]}" -n "${NS}" get events --sort-by=.lastTimestamp | tail -n 25 || true
echo ""

if command -v curl >/dev/null 2>&1; then
  echo "== mission control /ops/status (best-effort) =="
  set +e
  curl -fsS --max-time 3 "${MISSION_CONTROL_URL%/}/ops/status"
  rc=$?
  set -e
  if [[ "${rc}" != "0" ]]; then
    echo "WARN: unable to reach ${MISSION_CONTROL_URL%/}/ops/status (rc=${rc})" >&2
  else
    echo ""
  fi
else
  echo "INFO: curl not found; skipping /ops/status probe"
fi

