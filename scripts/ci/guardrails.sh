#!/usr/bin/env bash
#
# CI Guardrails (SAFE / READ-ONLY)
#
# Purpose:
# - Catch "YAML/CLI disasters" early with fast, deterministic checks.
# - Enforce guardrails without modifying any deployment/runtime pipelines.
#
# What this does:
# - Validates YAML syntax across tracked YAML files.
# - Runs bash syntax + variable-usage checks (ShellCheck + custom guards).
# - Blocks floating image tags like ":latest" (pin tags or use digests).
#
# This script is intentionally non-destructive: it only reads files and exits
# non-zero with clear, actionable error messages when a violation is found.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "${REPO_ROOT}"

echo "Running CI guardrails..."
echo "Repo root: ${REPO_ROOT}"

python3 "${REPO_ROOT}/scripts/ci/validate_yaml_syntax.py"
bash "${REPO_ROOT}/scripts/ci/check_bash_guardrails.sh"
python3 "${REPO_ROOT}/scripts/ci/check_no_latest_tags.py"

echo "OK: CI guardrails passed."

