#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 - Postmortem Replay (read-only)
#
# Wraps scripts/replay_from_logs.py and writes a timestamped artifact under audit_artifacts/.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/postmortem_replay.sh [--output-dir <dir>] [log1 [log2 ...]]

Notes:
  - If no log files are provided, reads from stdin.
  - Produces: replay_timeline.md
EOF
}

OUT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUT_DIR="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      break ;;
  esac
done

STAMP="$(date -u +'%Y%m%dT%H%M%SZ')"
if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="${ROOT_DIR}/audit_artifacts/postmortem_replay/${STAMP}"
fi
mkdir -p "${OUT_DIR}"

OUT_MD="${OUT_DIR}/replay_timeline.md"

python3 "${ROOT_DIR}/scripts/replay_from_logs.py" --output "${OUT_MD}" "$@"

echo "OK: wrote ${OUT_MD}"

