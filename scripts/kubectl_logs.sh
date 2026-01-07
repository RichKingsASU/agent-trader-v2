#!/usr/bin/env bash
set -euo pipefail

AGENT="${AGENT:-}"
NAMESPACE="${NAMESPACE:-default}"
CONTEXT="${CONTEXT:-}"
TAIL="${TAIL:-200}"
SINCE="${SINCE:-}"

if [[ -z "${AGENT}" ]]; then
  echo "ERROR: AGENT is required (example: make logs AGENT=strategy-engine)" >&2
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

since_args=()
if [[ -n "${SINCE}" ]]; then
  since_args+=(--since="${SINCE}")
fi

echo "context:   ${CONTEXT:-<current>}"
echo "namespace: ${NAMESPACE}"
echo "agent:     ${AGENT}"
echo ""

if kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get deploy "${AGENT}" >/dev/null 2>&1; then
  echo "== kubectl logs deploy/${AGENT} =="
  exec kubectl "${ctx_args[@]}" -n "${NAMESPACE}" logs -f "deploy/${AGENT}" --all-containers=true --tail="${TAIL}" "${since_args[@]}"
fi

if kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get statefulset "${AGENT}" >/dev/null 2>&1; then
  echo "== kubectl logs statefulset/${AGENT} =="
  exec kubectl "${ctx_args[@]}" -n "${NAMESPACE}" logs -f "statefulset/${AGENT}" --all-containers=true --tail="${TAIL}" "${since_args[@]}"
fi

pod=""
pod="$(kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get pods -l "app.kubernetes.io/instance=${AGENT}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
if [[ -z "${pod}" ]]; then
  pod="$(kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get pods -l "app=${AGENT}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
fi

if [[ -z "${pod}" ]]; then
  echo "ERROR: could not find Deployment/StatefulSet/Pod for AGENT='${AGENT}' in namespace '${NAMESPACE}'" >&2
  echo "" >&2
  echo "Try:" >&2
  echo "  kubectl ${ctx_args[*]} -n ${NAMESPACE} get deploy,statefulset,pods -o wide" >&2
  exit 2
fi

echo "== kubectl logs pod/${pod} =="
exec kubectl "${ctx_args[@]}" -n "${NAMESPACE}" logs -f "pod/${pod}" --all-containers=true --tail="${TAIL}" "${since_args[@]}"

