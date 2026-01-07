#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 release tag helper.
# - Creates a local annotated tag: v2-release-YYYYMMDD-HHMM
# - Includes git SHA in tag message
# - NEVER pushes automatically (prints the push command)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd git

cd "${ROOT_DIR}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree is dirty; refusing to tag." >&2
  echo "" >&2
  git status --porcelain >&2
  exit 1
fi

SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short HEAD)"
TS_UTC="$(date -u +%Y%m%d-%H%M)"
TAG="v2-release-${TS_UTC}"

if git rev-parse "${TAG}" >/dev/null 2>&1; then
  echo "ERROR: tag already exists: ${TAG}" >&2
  exit 1
fi

git tag -a "${TAG}" -m "AgentTrader v2 release tag

tag=${TAG}
git_sha=${SHA}
created_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
"

echo "OK: created local tag: ${TAG} (${SHORT_SHA})"
echo
echo "To push the tag (explicit operator action):"
echo "  git push origin ${TAG}"

