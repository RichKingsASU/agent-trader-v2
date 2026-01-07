#!/usr/bin/env bash
set -euo pipefail

# Deterministic deploy wrapper for AgentTrader v2.
# - runs pre-deploy guardrails (fail-fast)
# - applies k8s manifests
# - waits for rollout on v2 workloads
# - runs report script if present

NS="default"
K8S_DIR="k8s/"
PROJECT=""
EXPECTED_CONTEXT=""
ALLOW_UNKNOWN_IMAGES="0"

usage() {
  cat <<'EOF'
Usage: ./scripts/deploy_v2.sh [options]

Options:
  --namespace <ns>            Kubernetes namespace (default: "default")
  --k8s-dir <dir>             Manifests directory (default: "k8s/")
  --project <gcp-project-id>   Optional GCP project id (passed to guard)
  --expected-context <ctx>     Expected kubectl context (passed to guard)
  --allow-unknown-images       Allow images that cannot be validated (NOT recommended)
  -h, --help                   Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) NS="${2:?}"; shift 2;;
    --k8s-dir) K8S_DIR="${2:?}"; shift 2;;
    --project) PROJECT="${2:?}"; shift 2;;
    --expected-context) EXPECTED_CONTEXT="${2:?}"; shift 2;;
    --allow-unknown-images) ALLOW_UNKNOWN_IMAGES="1"; shift 1;;
    -h|--help) usage; exit 0;;
    *) echo "ERROR: Unknown arg: $1" >&2; usage; exit 2;;
  esac
done

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "ERROR: Not inside a git repository. Refusing."
  exit 1
fi
cd "${ROOT}"

guard_args=(--namespace "${NS}" --k8s-dir "${K8S_DIR}")
if [[ -n "${PROJECT}" ]]; then guard_args+=(--project "${PROJECT}"); fi
if [[ -n "${EXPECTED_CONTEXT}" ]]; then guard_args+=(--expected-context "${EXPECTED_CONTEXT}"); fi
if [[ "${ALLOW_UNKNOWN_IMAGES}" == "1" ]]; then guard_args+=(--allow-unknown-images); fi

./scripts/predeploy_guard.sh "${guard_args[@]}"

echo ""
echo "== kubectl apply (${K8S_DIR}) =="
kubectl apply -f "${K8S_DIR}"

echo ""
echo "== rollout status (app.kubernetes.io/part-of=agent-trader-v2) =="
resources="$(kubectl -n "${NS}" get deploy,statefulset -l app.kubernetes.io/part-of=agent-trader-v2 -o name 2>/dev/null || true)"
if [[ -z "${resources}" ]]; then
  echo "WARN: No deployments/statefulsets found with label app.kubernetes.io/part-of=agent-trader-v2 in namespace ${NS}"
else
  while IFS= read -r r; do
    [[ -z "${r}" ]] && continue
    echo "kubectl -n ${NS} rollout status ${r}"
    kubectl -n "${NS}" rollout status "${r}" --timeout=300s
  done <<< "${resources}"
fi

echo ""
if [[ -x "./scripts/report_v2_deploy.sh" ]]; then
  echo "== report_v2_deploy =="
  ./scripts/report_v2_deploy.sh || true
else
  echo "== report_v2_deploy =="
  echo "INFO: ./scripts/report_v2_deploy.sh not found or not executable (skipping)"
fi
