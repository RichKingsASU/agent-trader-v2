#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/audit_artifacts"

mkdir -p "${OUT_DIR}"

# Non-interactive / no pagers (best-effort)
export KUBECTL_PAGER="${KUBECTL_PAGER:-}"
export PAGER=cat
export GIT_PAGER=cat
export LESS=-FRSX

python3 "${ROOT_DIR}/scripts/report_v2_deploy.py" "$@"

echo "OK: wrote:"
echo " - ${OUT_DIR}/deploy_report.md"
echo " - ${OUT_DIR}/deploy_report.json"

