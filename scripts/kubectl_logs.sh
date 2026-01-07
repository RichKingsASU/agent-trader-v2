#!/usr/bin/env bash
set -euo pipefail

# Safe log tail helper for AgentTrader v2.
#
# - Tails logs for a single workload by name (deployment preferred, then statefulset)
# - Supports optional --context for deterministic cluster targeting

NS="default"
CTX=""
AGENT=""
TAIL="${TAIL:-200}"
SINCE="${SINCE:-1h}"

usage() {
  cat <<'EOF'
Usage: ./scripts/kubectl_logs.sh --agent <name> [--namespace <ns>] [--context <ctx>]

Env:
  TAIL   Number of lines to tail (default: 200)
  SINCE  Lookback window (default: 1h)

Examples:
  ./scripts/kubectl_logs.sh --namespace trading-floor --agent strategy-engine
  TAIL=500 SINCE=30m ./scripts/kubectl_logs.sh --agent marketdata-mcp-server
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n) NS="${2:?}"; shift 2;;
    --context) CTX="${2:?}"; shift 2;;
    --agent) AGENT="${2:?}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: unknown arg: $1" >&2; usage; exit 2;;
  esac
done

if [[ -z "${AGENT}" ]]; then
  echo "ERROR: --agent is required" >&2
  exit 2
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not found. Install kubectl or run in an environment that provides it." >&2
  exit 2
fi

kargs=()
if [[ -n "${CTX}" ]]; then
  kargs+=(--context "${CTX}")
fi

if kubectl "${kargs[@]}" -n "${NS}" get deploy "${AGENT}" >/dev/null 2>&1; then
  echo "kubectl -n ${NS} logs -f deploy/${AGENT} --tail=${TAIL} --since=${SINCE}"
  exec kubectl "${kargs[@]}" -n "${NS}" logs -f "deploy/${AGENT}" --tail="${TAIL}" --since="${SINCE}"
fi

if kubectl "${kargs[@]}" -n "${NS}" get sts "${AGENT}" >/dev/null 2>&1; then
  echo "kubectl -n ${NS} logs -f sts/${AGENT} --tail=${TAIL} --since=${SINCE}"
  exec kubectl "${kargs[@]}" -n "${NS}" logs -f "sts/${AGENT}" --tail="${TAIL}" --since="${SINCE}"
fi

echo "ERROR: no deployment/statefulset named '${AGENT}' found in namespace '${NS}'" >&2
echo "HINT: run: kubectl ${CTX:+--context ${CTX}} -n ${NS} get deploy,sts" >&2
exit 1

