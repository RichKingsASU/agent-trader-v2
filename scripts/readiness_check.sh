#!/usr/bin/env bash
set -euo pipefail

# Readiness check for AgentTrader v2 (Kubernetes)
# - Fails if kubectl missing or cluster unreachable
# - Fails if workloads are not ready
# - Enforces safety: kill-switch must be present and set to EXECUTION_HALTED=1

NAMESPACE="${NAMESPACE:-default}"
CONTEXT="${CONTEXT:-}"
LABEL_SELECTOR="${LABEL_SELECTOR:-app.kubernetes.io/part-of=agent-trader-v2}"
TIMEOUT="${TIMEOUT:-300s}"
MISSION_CONTROL_URL="${MISSION_CONTROL_URL:-http://agenttrader-mission-control}"
STRICT_MISSION_CONTROL="${STRICT_MISSION_CONTROL:-0}"

ctx_args=()
if [[ -n "${CONTEXT}" ]]; then
  ctx_args+=(--context "${CONTEXT}")
fi

if ! command -v kubectl >/dev/null 2>&1; then
  echo "ERROR: kubectl not installed (readiness requires cluster access)" >&2
  exit 2
fi

if ! kubectl "${ctx_args[@]}" version --request-timeout=5s >/dev/null 2>&1; then
  echo "ERROR: cluster unreachable (check kubectl context/auth/RBAC)" >&2
  exit 2
fi

echo "context:   ${CONTEXT:-<current>}"
echo "namespace: ${NAMESPACE}"
echo "selector:  ${LABEL_SELECTOR}"
echo "timeout:   ${TIMEOUT}"
echo ""

echo "== safety: kill-switch =="
halted="$(kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}' 2>/dev/null || true)"
if [[ -z "${halted}" ]]; then
  echo "ERROR: configmap/agenttrader-kill-switch missing in namespace '${NAMESPACE}'" >&2
  exit 1
fi
if [[ "${halted}" != "1" ]]; then
  echo "ERROR: EXECUTION_HALTED is '${halted}' (expected '1'). Refusing readiness." >&2
  exit 1
fi
echo "OK: EXECUTION_HALTED=1"
echo ""

fail=0

echo "== rollout: deployments =="
deploys="$(kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get deploy -l "${LABEL_SELECTOR}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
if [[ -z "${deploys}" ]]; then
  echo "(none found)"
else
  while IFS= read -r d; do
    [[ -z "${d}" ]] && continue
    echo "- deploy/${d}"
    if ! kubectl "${ctx_args[@]}" -n "${NAMESPACE}" rollout status "deploy/${d}" --timeout="${TIMEOUT}"; then
      fail=1
    fi
  done <<< "${deploys}"
fi
echo ""

echo "== rollout: statefulsets =="
sts="$(kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get statefulset -l "${LABEL_SELECTOR}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
if [[ -z "${sts}" ]]; then
  echo "(none found)"
else
  while IFS= read -r s; do
    [[ -z "${s}" ]] && continue
    echo "- statefulset/${s}"
    if ! kubectl "${ctx_args[@]}" -n "${NAMESPACE}" rollout status "statefulset/${s}" --timeout="${TIMEOUT}"; then
      fail=1
    fi
  done <<< "${sts}"
fi
echo ""

echo "== pods summary =="
kubectl "${ctx_args[@]}" -n "${NAMESPACE}" get pods -l "${LABEL_SELECTOR}" -o wide || true
echo ""

echo "== mission control probe (best-effort) =="
if command -v curl >/dev/null 2>&1; then
  url="${MISSION_CONTROL_URL%/}/ops/status"
  if curl -fsS --max-time 2 "${url}" >/dev/null; then
    echo "OK: ${url}"
  else
    msg="WARN: unable to reach ${url}"
    if [[ "${STRICT_MISSION_CONTROL}" == "1" ]]; then
      echo "ERROR: ${msg}" >&2
      fail=1
    else
      echo "${msg}"
    fi
  fi
else
  echo "SKIP: curl not installed"
fi

if [[ "${fail}" -ne 0 ]]; then
  echo ""
  echo "NOT READY"
  exit 1
fi

echo ""
echo "READY"

