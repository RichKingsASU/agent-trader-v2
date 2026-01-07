#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 - Config Snapshot (read-only)
#
# Captures a deterministic snapshot manifest (checksums + pointers) of operational config.
# This script MUST NOT modify runtime state.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/capture_config_snapshot.sh [--output-dir <dir>] [--lkg]

Options:
  --output-dir <dir>   Output directory for snapshot artifacts
  --lkg                Write to audit_artifacts/lkg/<YYYY-MM-DD>/ (immutable baseline)
EOF
}

OUT_DIR=""
LKG="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUT_DIR="${2:-}"; shift 2 ;;
    --lkg)
      LKG="1"; shift 1 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
STAMP_UTC="$(date -u +'%Y%m%dT%H%M%SZ')"
DAY_NY="$(TZ=America/New_York date +'%Y-%m-%d')"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
GIT_BRANCH="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "UNKNOWN")"

MODE="ad-hoc snapshot"
if [[ "${LKG}" == "1" ]]; then
  MODE="LKG (immutable baseline)"
fi

if [[ -z "${OUT_DIR}" ]]; then
  if [[ "${LKG}" == "1" ]]; then
    OUT_DIR="${ROOT_DIR}/audit_artifacts/lkg/${DAY_NY}"
  else
    OUT_DIR="${ROOT_DIR}/audit_artifacts/config_snapshot/${STAMP_UTC}"
  fi
fi

mkdir -p "${OUT_DIR}"

MD="${OUT_DIR}/config_snapshot.md"
SUMS="${OUT_DIR}/config_snapshot.sha256"

sha_cmd="sha256sum"
if ! command -v sha256sum >/dev/null 2>&1; then
  if command -v shasum >/dev/null 2>&1; then
    sha_cmd="shasum -a 256"
  else
    echo "ERROR: need sha256sum (or shasum) to compute checksums" >&2
    exit 1
  fi
fi

targets=(
  "k8s"
  "config"
  "infra"
  "docs/KILL_SWITCH.md"
  "docs/MARKETDATA_HEALTH_CONTRACT.md"
  "requirements.txt"
)

{
  echo "## AgentTrader v2 — Config Snapshot"
  echo
  echo "- **Generated (UTC)**: ${NOW_UTC}"
  echo "- **Git SHA**: \`${GIT_SHA}\`"
  echo "- **Git branch**: \`${GIT_BRANCH}\`"
  echo "- **Mode**: ${MODE}"
  echo "- **Output dir**: \`${OUT_DIR}\`"
  echo
  echo "### Included targets (best-effort)"
  echo
  for t in "${targets[@]}"; do
    echo "- \`${t}\`"
  done
  echo
  echo "### Checksums (sha256)"
  echo
  echo "> See \`config_snapshot.sha256\` for the canonical list."
  echo
} > "${MD}"

: > "${SUMS}"

add_path() {
  local rel="$1"
  local abs="${ROOT_DIR}/${rel}"
  if [[ -d "${abs}" ]]; then
    while IFS= read -r -d '' f; do
      # Write checksum lines as: <sha>  <relative_path>
      local relpath="${f#${ROOT_DIR}/}"
      ${sha_cmd} "${f}" | sed "s#  .*#  ${relpath}#" >> "${SUMS}"
    done < <(find "${abs}" -type f -print0 2>/dev/null || true)
    return 0
  fi
  if [[ -f "${abs}" ]]; then
    ${sha_cmd} "${abs}" | sed "s#  .*#  ${rel}#" >> "${SUMS}"
    return 0
  fi
  echo "WARN: missing target ${rel}" >> "${MD}"
  return 0
}

for t in "${targets[@]}"; do
  add_path "${t}"
done

# Sort deterministically (file paths)
if command -v sort >/dev/null 2>&1; then
  sort -k2,2 "${SUMS}" -o "${SUMS}"
fi

LINE_COUNT="0"
if command -v wc >/dev/null 2>&1; then
  # shellcheck disable=SC2012
  LINE_COUNT="$(wc -l "${SUMS}" 2>/dev/null | awk '{print $1}' || echo 0)"
fi

{
  echo '```text'
  sed -n '1,120p' "${SUMS}"
  if [[ "${LINE_COUNT}" -gt 120 ]]; then
    echo "... (truncated; see full file)"
  fi
  echo '```'
  echo
  echo "### Immutability"
  echo
  if [[ "${LKG}" == "1" ]]; then
    echo "- This snapshot is **immutable** once created (LKG baseline)."
    echo "- If you need an update, create a new day’s LKG directory."
  else
    echo "- This snapshot is evidence for an investigation; do not edit in place."
  fi
  echo
  echo "> This snapshot is read-only. It must never enable execution."
} >> "${MD}"

echo "OK: wrote:"
echo " - ${MD}"
echo " - ${SUMS}"

