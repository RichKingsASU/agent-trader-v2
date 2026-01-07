#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 — Config snapshot (read-only)
#
# Captures repo + cluster configuration *without secrets* into a timestamped
# directory under audit_artifacts/config_snapshots/.
#
# Writes:
# - audit_artifacts/config_snapshots/<UTC>/meta.txt
# - audit_artifacts/config_snapshots/<UTC>/repo_files/...
# - audit_artifacts/config_snapshots/<UTC>/k8s_listings/...
#
# Safety:
# - Does NOT apply/patch/scale any resources
# - Does NOT print secret values (only names/metadata)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_ROOT="${ROOT_DIR}/audit_artifacts/config_snapshots"

TS_UTC="$(date -u +'%Y%m%dT%H%M%SZ')"
OUT_DIR="${OUT_ROOT}/${TS_UTC}"
REPO_OUT="${OUT_DIR}/repo_files"
K8S_OUT="${OUT_DIR}/k8s_listings"

mkdir -p "${REPO_OUT}" "${K8S_OUT}"

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
Usage: ./scripts/capture_config_snapshot.sh [--namespace <ns>]

Environment:
  NAMESPACE  Namespace to snapshot (default: trading-floor)
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
  echo "agenttrader_v2_config_snapshot=1"
  echo "generated_utc=${TS_UTC}"
  echo "git_sha=${git_sha}"
  echo "git_branch=${git_branch}"
  echo "namespace=${NS}"
  echo "kubectl_context=${kube_context}"
} > "${OUT_DIR}/meta.txt"

echo "== AgentTrader v2 config snapshot (read-only) =="
echo "Wrote: ${OUT_DIR}"

echo
echo "== 1) Repo config capture (read-only) =="

# Copy key config sources (best-effort; keep structure)
copy_if_exists() {
  local rel="$1"
  if [[ -e "${ROOT_DIR}/${rel}" ]]; then
    mkdir -p "$(dirname "${REPO_OUT}/${rel}")"
    cp -R "${ROOT_DIR}/${rel}" "${REPO_OUT}/${rel}" 2>/dev/null || true
  fi
}

copy_if_exists "config/preflight.yaml"
copy_if_exists "configs/agents/agents.yaml"
copy_if_exists "configs/strategies"
copy_if_exists "k8s"
copy_if_exists "docs/ops/status_contract.md"
copy_if_exists "ops/PRODUCTION_LOCK.md"

echo "OK: copied repo config sources (best-effort)."

echo
echo "== 2) Cluster listings (names/metadata only; no secret values) =="
if command -v kubectl >/dev/null 2>&1; then
  {
    echo "context=$(kubectl config current-context 2>/dev/null || echo UNKNOWN)"
    echo "cluster=$(kubectl config view --minify -o jsonpath='{.contexts[0].context.cluster}' 2>/dev/null || echo UNKNOWN)"
    echo "user=$(kubectl config view --minify -o jsonpath='{.contexts[0].context.user}' 2>/dev/null || echo UNKNOWN)"
  } > "${K8S_OUT}/kubectl.meta" || true

  kubectl -n "${NS}" get deploy,sts,svc,job -o wide > "${K8S_OUT}/workloads.txt" 2>&1 || true
  kubectl -n "${NS}" get pods -o wide > "${K8S_OUT}/pods.txt" 2>&1 || true
  kubectl -n "${NS}" get events --sort-by=.lastTimestamp > "${K8S_OUT}/events.txt" 2>&1 || true

  # ConfigMaps are allowed (no secrets). Include kill-switch ConfigMap YAML for evidence.
  kubectl -n "${NS}" get configmap -o name > "${K8S_OUT}/configmaps.names.txt" 2>&1 || true
  kubectl -n "${NS}" get configmap agenttrader-kill-switch -o yaml > "${K8S_OUT}/kill_switch_configmap.yaml" 2>&1 || true

  # Secrets: names only (never export secret yaml/data).
  kubectl -n "${NS}" get secret -o name > "${K8S_OUT}/secrets.names.txt" 2>&1 || true

  echo "OK: cluster listings captured (best-effort)."
else
  echo "SKIP: kubectl not available."
fi

echo
echo "Done."

