#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "${REPO_ROOT}/audit_artifacts/blueprints"
mkdir -p "${REPO_ROOT}/docs"

python3 "${REPO_ROOT}/scripts/generate_blueprint.py"

echo ""
echo "Blueprint outputs:"
echo " - ${REPO_ROOT}/docs/BLUEPRINT.md"
echo " - ${REPO_ROOT}/audit_artifacts/blueprints/BLUEPRINT_<YYYYMMDD_HHMM>.md"

