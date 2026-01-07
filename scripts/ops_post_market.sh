#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 ops snapshot (POST-MARKET)
# - Read-only: does not patch resources, change AGENT_MODE, or toggle kill-switch.
# - Produces audit artifacts under audit_artifacts/ops_runs/.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_ROOT="${ROOT_DIR}/audit_artifacts"

TS_UTC="$(date -u +'%Y%m%dT%H%M%SZ')"
RUN_DIR="${OUT_ROOT}/ops_runs/${TS_UTC}_post_market"

mkdir -p "${RUN_DIR}"

export PAGER=cat
export GIT_PAGER=cat
export LESS=-FRSX
export KUBECTL_PAGER="${KUBECTL_PAGER:-}"

NS="${TRADING_FLOOR_NAMESPACE:-${NAMESPACE:-trading-floor}}"
LABEL_SELECTOR="${TRADING_FLOOR_LABEL_SELECTOR:-app.kubernetes.io/part-of=agent-trader-v2}"
MARKETDATA_HEALTH_URL="${MARKETDATA_HEALTH_URL:-http://127.0.0.1:8080/healthz}"

git_sha="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
git_branch="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo UNKNOWN)"

{
  echo "agenttrader_v2_ops_snapshot: post_market"
  echo "generated_utc=${TS_UTC}"
  echo "git_sha=${git_sha}"
  echo "git_branch=${git_branch}"
  echo "namespace=${NS}"
  echo "label_selector=${LABEL_SELECTOR}"
  echo "marketdata_health_url=${MARKETDATA_HEALTH_URL}"
} > "${RUN_DIR}/meta.txt"

echo "== AgentTrader v2 ops snapshot (post-market) =="
echo "Wrote: ${RUN_DIR}"

echo
echo "== 1) Deployment report (read-only) =="
if [[ -x "${ROOT_DIR}/scripts/report_v2_deploy.sh" ]] && command -v python3 >/dev/null 2>&1; then
  "${ROOT_DIR}/scripts/report_v2_deploy.sh" --namespace "${NS}" "$@" >/dev/null 2>&1 || true
  if [[ -f "${OUT_ROOT}/deploy_report.md" ]]; then
    cp -f "${OUT_ROOT}/deploy_report.md" "${RUN_DIR}/deploy_report.md" || true
  fi
  if [[ -f "${OUT_ROOT}/deploy_report.json" ]]; then
    cp -f "${OUT_ROOT}/deploy_report.json" "${RUN_DIR}/deploy_report.json" || true
  fi
  echo "OK: deploy report captured (best-effort)."
else
  echo "SKIP: report_v2_deploy.sh or python3 not available."
fi

echo
echo "== 2) Marketdata heartbeat sample (read-only) =="
if command -v curl >/dev/null 2>&1; then
  http_code="$(
    curl -sS -m 5 -o "${RUN_DIR}/marketdata_health.json" -w "%{http_code}" "${MARKETDATA_HEALTH_URL}" || true
  )"
  echo "marketdata_health_http_code=${http_code}" > "${RUN_DIR}/marketdata_health.status"
  echo "OK: sampled ${MARKETDATA_HEALTH_URL} (http=${http_code})."
else
  echo "SKIP: curl not available."
fi

echo
echo "== 3) Cluster snapshot (read-only, best-effort) =="
if command -v kubectl >/dev/null 2>&1; then
  {
    echo "context=$(kubectl config current-context 2>/dev/null || echo UNKNOWN)"
    echo "cluster=$(kubectl config view --minify -o jsonpath='{.contexts[0].context.cluster}' 2>/dev/null || echo UNKNOWN)"
    echo "user=$(kubectl config view --minify -o jsonpath='{.contexts[0].context.user}' 2>/dev/null || echo UNKNOWN)"
  } > "${RUN_DIR}/kubectl.meta" || true

  kubectl -n "${NS}" get deploy,statefulset,job,svc -l "${LABEL_SELECTOR}" -o wide > "${RUN_DIR}/k8s.workloads.txt" 2>&1 || true
  kubectl -n "${NS}" get pods -l "${LABEL_SELECTOR}" -o wide > "${RUN_DIR}/k8s.pods.txt" 2>&1 || true
  kubectl -n "${NS}" get configmap agenttrader-kill-switch -o yaml > "${RUN_DIR}/k8s.kill_switch_configmap.yaml" 2>&1 || true
  kubectl -n "${NS}" get events --sort-by=.lastTimestamp > "${RUN_DIR}/k8s.events.txt" 2>&1 || true

  # Tail logs for critical workloads (best-effort).
  kubectl -n "${NS}" logs deploy/marketdata-mcp-server --tail=200 > "${RUN_DIR}/logs.marketdata-mcp-server.txt" 2>&1 || true
  kubectl -n "${NS}" logs statefulset/gamma-strategy --tail=200 > "${RUN_DIR}/logs.gamma-strategy.txt" 2>&1 || true
  kubectl -n "${NS}" logs statefulset/whale-strategy --tail=200 > "${RUN_DIR}/logs.whale-strategy.txt" 2>&1 || true

  echo "OK: cluster snapshot captured (best-effort)."
else
  echo "SKIP: kubectl not available."
fi

echo
echo "Done."

