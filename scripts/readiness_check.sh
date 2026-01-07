#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 - Readiness Check (read-only)
#
# ABSOLUTE RULES:
# - Do NOT enable trading execution.
# - Do NOT mutate cluster state.
# - Only observe and write artifacts under audit_artifacts/.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/readiness_check.sh [--namespace <ns>] [--output-dir <dir>] [--allow-no-cluster]

Options:
  --namespace <ns>       Kubernetes namespace to check (default: trading-floor)
  --output-dir <dir>     Output directory for artifacts
  --allow-no-cluster     Do not fail if kubectl/cluster access is unavailable (dry-run mode)
EOF
}

NS="trading-floor"
ALLOW_NO_CLUSTER="0"
OUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace)
      NS="${2:-}"; shift 2 ;;
    --output-dir)
      OUT_DIR="${2:-}"; shift 2 ;;
    --allow-no-cluster)
      ALLOW_NO_CLUSTER="1"; shift 1 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
STAMP="$(date -u +'%Y%m%dT%H%M%SZ')"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
GIT_BRANCH="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "UNKNOWN")"

if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="${ROOT_DIR}/audit_artifacts/readiness_check/${STAMP}"
fi
mkdir -p "${OUT_DIR}"

REPORT_MD="${OUT_DIR}/readiness_report.md"

fail=0
reasons=()

note() { echo "- $*" >> "${REPORT_MD}"; }
fail_with() { fail=1; reasons+=("$*"); }

{
  echo "## AgentTrader v2 — Readiness Check"
  echo
  echo "- **Generated (UTC)**: ${NOW_UTC}"
  echo "- **Git SHA**: \`${GIT_SHA}\`"
  echo "- **Git branch**: \`${GIT_BRANCH}\`"
  echo "- **Namespace**: \`${NS}\`"
  echo
  echo "### Checks"
  echo
} > "${REPORT_MD}"

# 1) Backend compile sanity (read-only)
if command -v python3 >/dev/null 2>&1; then
  if python3 -m compileall "${ROOT_DIR}/backend" >/dev/null 2>&1; then
    note "**backend compile**: PASS"
  else
    note "**backend compile**: FAIL"
    fail_with "backend compileall failed"
  fi
else
  note "**python3 present**: FAIL"
  fail_with "python3 not found"
fi

# 2) Repo guardrail: forbid AGENT_MODE=EXECUTE anywhere in k8s manifests (read-only)
if command -v grep >/dev/null 2>&1; then
  if grep -R -n -E 'AGENT_MODE[[:space:]]*[:=][[:space:]]*("?EXECUTE"?)' "${ROOT_DIR}/k8s" >/dev/null 2>&1; then
    note "**k8s guardrail (no AGENT_MODE=EXECUTE)**: FAIL"
    fail_with "found forbidden AGENT_MODE=EXECUTE in k8s manifests"
  else
    note "**k8s guardrail (no AGENT_MODE=EXECUTE)**: PASS"
  fi
else
  note "**k8s guardrail scan**: WARN (grep not available)"
fi

# 3) Repo baseline: kill switch manifest defaults to HALTED (read-only)
KS_FILE="${ROOT_DIR}/k8s/05-kill-switch-configmap.yaml"
if [[ -f "${KS_FILE}" ]]; then
  if grep -n -E '^[[:space:]]*EXECUTION_HALTED:[[:space:]]*"?1"?' "${KS_FILE}" >/dev/null 2>&1; then
    note "**repo kill-switch default (EXECUTION_HALTED=1)**: PASS"
  else
    note "**repo kill-switch default (EXECUTION_HALTED=1)**: WARN (manifest not defaulting to 1)"
  fi
else
  note "**repo kill-switch manifest present**: FAIL"
  fail_with "missing k8s/05-kill-switch-configmap.yaml"
fi

# 4) Cluster check: kill switch must be ON (unless allow-no-cluster)
if command -v kubectl >/dev/null 2>&1; then
  KUBE_CONTEXT="$(kubectl config current-context 2>/dev/null || echo "UNKNOWN")"
  note "**kubectl context**: \`${KUBE_CONTEXT}\`"

  # Best-effort read-only query; do NOT patch/apply.
  set +e
  KS_VAL="$(kubectl -n "${NS}" get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}' 2>/dev/null)"
  rc=$?
  set -e

  if [[ $rc -ne 0 ]]; then
    note "**cluster kill-switch (EXECUTION_HALTED)**: ${ALLOW_NO_CLUSTER/1/WARN}/${ALLOW_NO_CLUSTER/0/FAIL} (unable to query configmap)"
    if [[ "${ALLOW_NO_CLUSTER}" != "1" ]]; then
      fail_with "unable to query cluster kill switch configmap (kubectl access/RBAC/context)"
    fi
  else
    KS_VAL="$(echo "${KS_VAL}" | tr -d '[:space:]' || true)"
    if [[ "${KS_VAL}" == "1" || "${KS_VAL,,}" == "true" ]]; then
      note "**cluster kill-switch (EXECUTION_HALTED)**: PASS (value=${KS_VAL})"
    else
      note "**cluster kill-switch (EXECUTION_HALTED)**: FAIL (value=${KS_VAL:-<empty>})"
      fail_with "cluster kill switch is not ON (expected EXECUTION_HALTED=1)"
    fi
  fi
else
  note "**kubectl present**: ${ALLOW_NO_CLUSTER/1/WARN}/${ALLOW_NO_CLUSTER/0/FAIL}"
  if [[ "${ALLOW_NO_CLUSTER}" != "1" ]]; then
    fail_with "kubectl not found; cannot verify cluster posture"
  fi
fi

{
  echo
  if [[ "${fail}" -eq 0 ]]; then
    echo "### Result"
    echo
    echo "**PASS**"
  else
    echo "### Result"
    echo
    echo "**FAIL**"
    echo
    echo "### Reasons"
    echo
    for r in "${reasons[@]}"; do
      echo "- ${r}"
    done
  fi
  echo
  echo "> This readiness check is read-only. It must never enable execution."
} >> "${REPORT_MD}"

if [[ "${fail}" -eq 0 ]]; then
  echo "PASS: readiness check OK (${REPORT_MD})"
  exit 0
fi

echo "FAIL: readiness check failed (${REPORT_MD})" >&2
exit 1

