#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

require_cmd() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || fail "missing required command: ${cmd}"
}

require_cmd git
require_cmd rg
require_cmd sed

REPO_ID="RichKingsASU/agent-trader-v2"
NOW_UTC="$(date -u +%Y%m%d-%H%M)"
LOCK_TS_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD)"

TAG="v2-lock-${NOW_UTC}"

LOCK_FILE="${ROOT_DIR}/ops/PRODUCTION_LOCK.md"
[[ -f "${LOCK_FILE}" ]] || fail "missing ${LOCK_FILE#${ROOT_DIR}/} (run lock generation first)"

# Lightweight extraction for tag metadata (best-effort).
CLUSTERS_LINE="$(rg -n '^\s*-\s+\*\*Kubernetes \(GKE\)\*\*:\s*' "${LOCK_FILE}" 2>/dev/null | head -n 1 | sed -E 's/^[0-9]+://')"
if [[ -z "${CLUSTERS_LINE}" ]]; then
  CLUSTERS_LINE="- **Kubernetes (GKE)**: trading-floor namespace"
fi

MSG="$(cat <<EOF
AgentTrader v2 — Production Lock Tag

lock_timestamp_utc: ${LOCK_TS_UTC}
repo_id: ${REPO_ID}
git_sha: ${GIT_SHA}
clusters_targeted:
${CLUSTERS_LINE}

Locked safety statements:
- Execution is DISABLED
- AGENT_MODE defaults OFF
- Kill-switch defaults SAFE

Artifact: ops/PRODUCTION_LOCK.md
EOF
)"

git -C "${ROOT_DIR}" tag -a "${TAG}" -m "${MSG}"

echo "OK: created tag ${TAG}"
echo
echo "Next steps (manual):"
echo "  git push origin ${TAG}"
echo
echo "To view tag message:"
echo "  git show ${TAG} --no-patch"
