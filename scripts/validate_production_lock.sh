#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

ok() {
  echo "OK: $*"
}

require_cmd() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || fail "missing required command: ${cmd}"
}

echo "AgentTrader v2 — validate production lock"

require_cmd git
require_cmd rg

# 1) repo must be clean
if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain 2>/dev/null || true)" ]]; then
  echo
  git -C "${ROOT_DIR}" status --porcelain || true
  fail "repo is dirty; commit/stash changes before validating the lock"
fi
if ! git -C "${ROOT_DIR}" diff --quiet; then
  fail "git diff is not empty"
fi
if ! git -C "${ROOT_DIR}" diff --cached --quiet; then
  fail "staged changes present"
fi
ok "repo working tree is clean"

# 2) lock artifact exists
[[ -f "${ROOT_DIR}/ops/PRODUCTION_LOCK.md" ]] || fail "missing ops/PRODUCTION_LOCK.md"
ok "found ops/PRODUCTION_LOCK.md"

# 3) required docs exist
for f in \
  "${ROOT_DIR}/docs/ops/go_no_go.md" \
  "${ROOT_DIR}/docs/ops/agent_mesh.md" \
  "${ROOT_DIR}/docs/ops/audit_pack.md"
do
  [[ -f "${f}" ]] || fail "missing required doc: ${f#${ROOT_DIR}/}"
done
ok "found required docs (go_no_go.md, agent_mesh.md, audit_pack.md)"

# 4) execution agent must be scaled 0 (manifest)
EXEC_DEP="${ROOT_DIR}/k8s/30-execution-agent-deployment.yaml"
[[ -f "${EXEC_DEP}" ]] || fail "missing manifest: k8s/30-execution-agent-deployment.yaml"
if ! rg -q '^\s*replicas:\s*0\s*$' "${EXEC_DEP}"; then
  fail "execution-agent manifest is not scaled to 0 (expected replicas: 0)"
fi
ok "execution-agent manifest scaled to 0"

# 5) no AGENT_MODE=EXECUTE anywhere in manifests/config
if rg -n 'AGENT_MODE\s*[:=]\s*"?EXECUTE"?' \
  "${ROOT_DIR}/k8s" "${ROOT_DIR}/infra" "${ROOT_DIR}/config" "${ROOT_DIR}/configs" >/dev/null 2>&1; then
  echo
  rg -n 'AGENT_MODE\s*[:=]\s*"?EXECUTE"?' "${ROOT_DIR}/k8s" "${ROOT_DIR}/infra" "${ROOT_DIR}/config" "${ROOT_DIR}/configs" || true
  fail "AGENT_MODE=EXECUTE detected (forbidden under production lock)"
fi
ok "no AGENT_MODE=EXECUTE detected in manifests/config"

# 6) kill-switch config present + safe default
KS="${ROOT_DIR}/k8s/05-kill-switch-configmap.yaml"
[[ -f "${KS}" ]] || fail "missing kill-switch manifest: k8s/05-kill-switch-configmap.yaml"
rg -q '^\s*name:\s*agenttrader-kill-switch\s*$' "${KS}" || fail "kill-switch ConfigMap name not found (expected agenttrader-kill-switch)"
rg -q '^\s*EXECUTION_HALTED:\s*"?1"?\s*$' "${KS}" || fail "kill-switch default not SAFE (expected EXECUTION_HALTED: \"1\")"
ok "kill-switch present and defaults SAFE (EXECUTION_HALTED=1)"

# 7) no :latest tags in locked manifests
if rg -n '\bimage:\s*\S+:latest\b' "${ROOT_DIR}/k8s" "${ROOT_DIR}/infra" >/dev/null 2>&1; then
  echo
  rg -n '\bimage:\s*\S+:latest\b' "${ROOT_DIR}/k8s" "${ROOT_DIR}/infra" || true
  fail "found :latest image tag usage (forbidden under production lock)"
fi
ok "no :latest image tags detected in k8s/ or infra/"

# 8) readiness_check must pass (if present)
if [[ -f "${ROOT_DIR}/scripts/readiness_check.sh" ]]; then
  require_cmd bash
  require_cmd python3
  require_cmd kubectl

  # execution-agent must be scaled 0 (live, if present)
  set +e
  LIVE_REPLICAS="$(kubectl -n trading-floor get deploy execution-agent -o jsonpath='{.spec.replicas}' 2>/dev/null)"
  LIVE_RC=$?
  set -e
  if [[ "${LIVE_RC}" == "0" ]]; then
    [[ "${LIVE_REPLICAS:-0}" == "0" ]] || fail "execution-agent is deployed and not scaled to 0 (replicas=${LIVE_REPLICAS})"
    ok "execution-agent live replica check: 0"
  else
    ok "execution-agent not deployed in cluster (acceptable; disabled baseline)"
  fi

  echo
  echo "Running readiness gate: ./scripts/readiness_check.sh --skip-preflight"
  if ! (cd "${ROOT_DIR}" && bash ./scripts/readiness_check.sh --skip-preflight); then
    echo
    echo "Readiness report (if generated): audit_artifacts/readiness_report.md" >&2
    fail "readiness_check.sh failed"
  fi
  ok "readiness_check.sh passed"
else
  ok "scripts/readiness_check.sh not present (skipping)"
fi

echo
ok "PRODUCTION LOCK VALIDATION PASSED"
