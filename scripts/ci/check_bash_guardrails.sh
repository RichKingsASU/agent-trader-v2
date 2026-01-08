#!/usr/bin/env bash
#
# Bash guardrails (SAFE / READ-ONLY).
#
# Enforces:
# - Bash syntax validity (bash -n)
# - Common GitHub-Actions-in-bash mistakes (e.g., `${{ ... }}` in .sh files)
# - Invalid bash variable usage patterns (hyphens in var names, export $VAR=...)
# - ShellCheck findings (prevents subtle quoting/word-splitting bugs)
#
# Why:
# - Broken bash often "works on my machine" and then bricks CI/CD.
# - These checks are fast and pinpoint the exact file/line.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "${REPO_ROOT}"

echo "--- Bash syntax validation (bash -n) ---"

mapfile -t SH_FILES < <(git ls-files '*.sh')

if [[ ${#SH_FILES[@]} -eq 0 ]]; then
  echo "OK: no tracked *.sh files found."
else
  for f in "${SH_FILES[@]}"; do
    # bash -n: parse only (no execution)
    if ! bash -n "${f}"; then
      echo "ERROR: bash syntax error in: ${f}" >&2
      echo "Fix the syntax error shown above. This check does not execute the script." >&2
      exit 1
    fi
  done
  echo "OK: bash -n parsed ${#SH_FILES[@]} scripts."
fi

echo "--- Bash variable usage guardrails (custom) ---"
python3 "${REPO_ROOT}/scripts/ci/check_bash_vars.py"

echo "--- ShellCheck (bash) ---"
if ! command -v shellcheck >/dev/null 2>&1; then
  echo "ERROR: shellcheck is required for bash guardrails but was not found on PATH." >&2
  echo "Fix (Ubuntu/Debian): sudo apt-get update && sudo apt-get install -y shellcheck" >&2
  exit 2
fi

# Keep this focused: shellcheck only the CI guard scripts themselves (and existing
# CI entrypoint scripts), so we don't fail the repo on unrelated legacy lint.
# The repo-wide protection is provided by `bash -n` + custom variable checks above.
mapfile -t SC_FILES < <(git ls-files 'scripts/ci/*.sh' 'scripts/ci_*.sh')
if [[ ${#SC_FILES[@]} -gt 0 ]]; then
  # -x: follow sourced files where possible
  # -s bash: force bash dialect
  shellcheck -x -s bash "${SC_FILES[@]}"
fi

echo "OK: bash guardrails passed."

