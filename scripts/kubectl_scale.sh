#!/usr/bin/env bash
set -euo pipefail

AGENT="${AGENT:-}"
REPLICAS="${REPLICAS:-}"
NAMESPACE="${NAMESPACE:-default}"
CONTEXT="${CONTEXT:-}"

if [[ -z "${AGENT}" ]] || [[ -z "${REPLICAS}" ]]; then
  echo "ERROR: AGENT and REPLICAS are required (example: make scale AGENT=strategy-engine REPLICAS=0)" >&2
  exit 2
fi

if ! [[ "${REPLICAS}" =~ ^[0-9]+$ ]]; then
  echo "ERROR: REPLICAS must be an integer, got '${REPLICAS}'" >&2
  exit 2
fi

ctx_args=()
if [[ -n "${CONTEXT}" ]]; then
  ctx_args+=(--context "${CONTEXT}")
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not installed" >&2
  exit 2
fi

if ! kubectl "${ctx_args[@]}" version --request-timeout=5s >/dev/null 2>&1; then
  echo "ERROR: cluster unreachable (check kubectl context/auth/RBAC)" >&2
  exit 2
fi

echo "context:   ${CONTEXT:-<current>}"
echo "namespace: ${NAMESPACE}"
echo "agent:     ${AGENT}"
echo "replicas:  ${REPLICAS}"
echo ""

if kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get deploy "${AGENT}" >/dev/null 2>&1; then
  kubectl "${ctx_args[@]}" -n "${NAMESPACE}" scale "deploy/${AGENT}" --replicas="${REPLICAS}"
  kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get "deploy/${AGENT}" -o wide
  exit 0
fi

if kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get statefulset "${AGENT}" >/dev/null 2>&1; then
  kubectl "${ctx_args[@]}" -n "${NAMESPACE}" scale "statefulset/${AGENT}" --replicas="${REPLICAS}"
  kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get "statefulset/${AGENT}" -o wide
  exit 0
fi

echo "ERROR: workload not found (expected Deployment/StatefulSet named '${AGENT}' in namespace '${NAMESPACE}')" >&2
exit 2

