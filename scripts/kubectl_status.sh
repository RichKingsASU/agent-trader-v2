#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-default}"
CONTEXT="${CONTEXT:-}"
LABEL_SELECTOR="${LABEL_SELECTOR:-app.kubernetes.io/part-of=agent-trader-v2}"
MISSION_CONTROL_URL="${MISSION_CONTROL_URL:-http://agenttrader-mission-control}"

ctx_args=()
if [[ -n "${CONTEXT}" ]]; then
  ctx_args+=(--context "${CONTEXT}")
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "WARN: kubectl not installed; cannot query cluster status."
  exit 0
fi

if ! kubectl "${ctx_args[@]}" version --request-timeout=5s >/dev/null 2>&1; then
  echo "WARN: cluster unreachable (check kubectl context/auth/RBAC)."
  echo "  context: ${CONTEXT:-<current>}"
  echo "  namespace: ${NAMESPACE}"
  exit 0
fi

echo "context:   ${CONTEXT:-<current>}"
echo "namespace: ${NAMESPACE}"
echo "selector:  ${LABEL_SELECTOR}"
echo ""

echo "== workloads =="
kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get deploy,statefulset -l "${LABEL_SELECTOR}" -o wide || true
echo ""

echo "== pods (agent-trader-v2) =="
kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get pods -l "${LABEL_SELECTOR}" -o wide || true
echo ""

echo "== services (agent-trader-v2) =="
kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get svc -l "${LABEL_SELECTOR}" -o wide || true
echo ""

echo "== kill-switch (cluster) =="
kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get configmap agenttrader-kill-switch -o yaml 2>/dev/null || \
  echo "WARN: configmap/agenttrader-kill-switch not found in namespace ${NAMESPACE}"

echo ""
echo "== mission control url (configured) =="
echo "${MISSION_CONTROL_URL}"

