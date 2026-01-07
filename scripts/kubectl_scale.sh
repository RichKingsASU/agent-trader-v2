#!/usr/bin/env bash
set -euo pipefail

# Safe scale helper for AgentTrader v2.
#
# - Scales a single deployment/statefulset by name
# - Supports optional --context for deterministic cluster targeting

NS="default"
CTX=""
AGENT=""
REPLICAS=""

usage() {
  cat <<'EOF'
Usage: ./scripts/kubectl_scale.sh --agent <name> --replicas <n> [--namespace <ns>] [--context <ctx>]

Examples:
  ./scripts/kubectl_scale.sh --namespace trading-floor --agent strategy-engine --replicas 2
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n) NS="${2:?}"; shift 2;;
    --context) CTX="${2:?}"; shift 2;;
    --agent) AGENT="${2:?}"; shift 2;;
    --replicas) REPLICAS="${2:?}"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: unknown arg: $1" >&2; usage; exit 2;;
  esac
done

if [[ -z "${AGENT}" ]]; then
  echo "ERROR: --agent is required" >&2
  exit 2
fi
if [[ -z "${REPLICAS}" ]]; then
  echo "ERROR: --replicas is required" >&2
  exit 2
fi
if ! [[ "${REPLICAS}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: --replicas must be a non-negative integer (got '${REPLICAS}')" >&2
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
  echo "kubectl -n ${NS} scale deploy/${AGENT} --replicas=${REPLICAS}"
  kubectl "${kargs[@]}" -n "${NS}" scale "deploy/${AGENT}" --replicas="${REPLICAS}"
  exit 0
fi

if kubectl "${kargs[@]}" -n "${NS}" get sts "${AGENT}" >/dev/null 2>&1; then
  echo "kubectl -n ${NS} scale sts/${AGENT} --replicas=${REPLICAS}"
  kubectl "${kargs[@]}" -n "${NS}" scale "sts/${AGENT}" --replicas="${REPLICAS}"
  exit 0
fi

echo "ERROR: no deployment/statefulset named '${AGENT}' found in namespace '${NS}'" >&2
echo "HINT: run: kubectl ${CTX:+--context ${CTX}} -n ${NS} get deploy,sts" >&2
exit 1

