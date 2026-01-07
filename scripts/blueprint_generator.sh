#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 — "Forever Loop" blueprint generator (read-only)
#
# Produces a timestamped inventory snapshot for operators and audits.
#
# Writes:
# - audit_artifacts/blueprints/<UTC>/blueprint.md
#
# Safety:
# - Read-only: does not apply/patch/scale any resources

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_ROOT="${ROOT_DIR}/audit_artifacts/blueprints"

TS_UTC="$(date -u +'%Y%m%dT%H%M%SZ')"
OUT_DIR="${OUT_ROOT}/${TS_UTC}"
OUT_MD="${OUT_DIR}/blueprint.md"

mkdir -p "${OUT_DIR}"

export KUBECTL_PAGER=""
export PAGER=cat
export GIT_PAGER=cat
export LESS=-FRSX

NS="${NAMESPACE:-trading-floor}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace|-n)
      NS="${2:-}"
      shift 2
      ;;
    --help|-h)
      cat <<EOF
Usage: ./scripts/blueprint_generator.sh [--namespace <ns>]

Environment:
  NAMESPACE  Namespace to inventory (default: trading-floor)
EOF
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

git_sha="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo UNKNOWN)"
git_branch="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo UNKNOWN)"
kube_context="UNKNOWN"
if command -v kubectl >/dev/null 2>&1; then
  kube_context="$(kubectl config current-context 2>/dev/null || echo UNKNOWN)"
fi

{
  echo "# AgentTrader v2 — Ops Blueprint"
  echo
  echo "- Generated (UTC): \`${TS_UTC}\`"
  echo "- Git SHA: \`${git_sha}\`"
  echo "- Git branch: \`${git_branch}\`"
  echo "- Namespace: \`${NS}\`"
  echo "- kubectl context: \`${kube_context}\`"
  echo
  echo "## Always-on services (post-lock default)"
  echo
  echo "- **marketdata-mcp-server**"
  echo "- **strategy-engine** (strategy runtime workloads)"
  echo "- **mission-control**"
  echo "- **ops-ui**"
  echo
  echo "## Health contract (operator-facing)"
  echo
  echo "- Prefer: \`GET /ops/status\` (see \`docs/ops/status_contract.md\`)"
  echo "- Fallback: \`GET /healthz\` (marketdata freshness gating)"
  echo "- Fallback: \`GET /health\` (basic liveness)"
  echo
  echo "## Production lock (guardrails)"
  echo
  echo "- Lock scope + rules: \`ops/PRODUCTION_LOCK.md\`"
  echo "- Absolute rule: **execution remains disabled** (no automation flips it)."
  echo
  echo "## Manifests of record (k8s)"
  echo
  echo "- \`k8s/20-marketdata-mcp-server-deployment-and-service.yaml\`"
  echo "- \`k8s/10-gamma-strategy-statefulset.yaml\`"
  echo "- \`k8s/11-whale-strategy-statefulset.yaml\`"
  echo "- \`k8s/mission-control/deployment.yaml\`"
  echo "- \`k8s/ops-ui/deployment.yaml\`"
  echo
  echo "## Agent inventory (mission-control static discovery)"
  echo
  echo "- \`configs/agents/agents.yaml\`"
  echo
  echo "## Cluster inventory (best-effort)"
  echo
  if command -v kubectl >/dev/null 2>&1; then
    echo "### Workloads (deploy/sts/svc) labeled as v2"
    echo
    echo '```text'
    kubectl -n "${NS}" get deploy,sts,svc -l app.kubernetes.io/part-of=agent-trader-v2 -o wide 2>&1 || true
    echo '```'
    echo
    echo "### Pods"
    echo
    echo '```text'
    kubectl -n "${NS}" get pods -l app.kubernetes.io/part-of=agent-trader-v2 -o wide 2>&1 || true
    echo '```'
    echo
    echo "### Kill-switch ConfigMap (evidence only; must remain halted by default)"
    echo
    echo '```text'
    kubectl -n "${NS}" get configmap agenttrader-kill-switch -o yaml 2>&1 || true
    echo '```'
    echo
  else
    echo "_kubectl not available; cluster inventory skipped._"
    echo
  fi
  echo "## References"
  echo
  echo "- Day 1 Ops playbook: \`docs/ops/day1_ops.md\`"
  echo "- Pre-market runbook: \`docs/ops/runbooks/pre_market.md\`"
  echo "- Post-market runbook: \`docs/ops/runbooks/post_market.md\`"
} > "${OUT_MD}"

echo "OK: wrote ${OUT_MD}"

