#!/usr/bin/env bash
set -euo pipefail

# Pre-deploy guardrails (read-only / no trading enablement)
#
# Goals:
# - Refuse obvious unsafe deploys (wrong repo / secrets / trading enabled by default).
# - Keep deterministic and minimal: no network calls, no builds.

REQUIRED_REPO_ID="${REQUIRED_REPO_ID:-agent-trader-v2}"
NAMESPACE="${NAMESPACE:-default}"
K8S_DIR="${K8S_DIR:-k8s}"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${ROOT}" ]]; then
  echo "ERROR: Not inside a git repository."
  exit 1
fi

cd "${ROOT}"

echo "== predeploy guard =="
echo "repo_root:  ${ROOT}"
echo "namespace:  ${NAMESPACE}"
echo "k8s_dir:    ${K8S_DIR}"
echo ""

if [[ ! -f ".repo_id" ]]; then
  echo "ERROR: Missing .repo_id at repo root. Refusing."
  echo "Fix: create .repo_id containing exactly: ${REQUIRED_REPO_ID}"
  exit 1
fi

REPO_ID="$(tr -d ' \n\r\t' < .repo_id)"
if [[ "${REPO_ID}" != "${REQUIRED_REPO_ID}" ]]; then
  echo "ERROR: .repo_id mismatch. Expected '${REQUIRED_REPO_ID}', got '${REPO_ID}'. Refusing."
  exit 1
fi

echo "== guardrails: secrets markers (tracked files) =="
if git grep -n -I -E \
  -e "-----BEGIN( [A-Z]+)? PRIVATE KEY-----" \
  -e "\"type\"[[:space:]]*:[[:space:]]*\"service_account\"" \
  -e "\"client_email\"[[:space:]]*:" \
  -e "\"private_key\"[[:space:]]*:" \
  -e "\"private_key_id\"[[:space:]]*:" \
  -- . >/dev/null; then
  echo "ERROR: possible secret material detected in tracked files."
  exit 1
fi

echo ""
echo "== guardrails: trading execution must be halted by default =="
KILL_SWITCH_FILE="${K8S_DIR}/05-kill-switch-configmap.yaml"
if [[ -f "${KILL_SWITCH_FILE}" ]]; then
  if ! grep -Eq '^[[:space:]]*EXECUTION_HALTED:[[:space:]]*"?1"?' "${KILL_SWITCH_FILE}"; then
    echo "ERROR: ${KILL_SWITCH_FILE} does not set EXECUTION_HALTED to \"1\"."
    echo "Refusing: do NOT enable trading execution via manifests."
    exit 1
  fi
  echo "OK: ${KILL_SWITCH_FILE} sets EXECUTION_HALTED=1"
else
  echo "WARN: ${KILL_SWITCH_FILE} not found; cannot verify default EXECUTION_HALTED=1"
fi

echo ""
echo "OK: guard passed"

