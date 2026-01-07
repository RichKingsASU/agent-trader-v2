#!/usr/bin/env bash
#
# Validate CI layout references (Cloud Build)
#
# Goal: prevent cloudbuild.yaml from referencing missing scripts / wrong paths.
#
set -euo pipefail

REPO_ROOT="$(
  git rev-parse --show-toplevel 2>/dev/null || pwd
)"

CLOUDBUILD_YAML="${REPO_ROOT}/cloudbuild.yaml"

fail=0

err() {
  echo "ERROR: $*" >&2
  fail=1
}

note() {
  echo "INFO: $*" >&2
}

require_file() {
  local rel="${1:?relative path required}"
  local abs="${REPO_ROOT}/${rel}"
  if [[ ! -f "${abs}" ]]; then
    err "missing required file: ${rel}"
  fi
}

note "Validating CI layout under ${REPO_ROOT}"

# Required invariants (repo-level)
require_file "cloudbuild.yaml"
require_file "scripts/ci_safety_guard.sh"

# Conditionally required: only if referenced by cloudbuild.yaml
if [[ -f "${CLOUDBUILD_YAML}" ]] && grep -qE '(^|[^A-Za-z0-9_./-])(\./)?scripts/smoke_check_imports\.py([^A-Za-z0-9_.-]|$)' "${CLOUDBUILD_YAML}"; then
  require_file "scripts/smoke_check_imports.py"
fi

# Discover scripts referenced by cloudbuild.yaml and verify they exist.
# We only validate paths under scripts/ to avoid false positives.
if [[ -f "${CLOUDBUILD_YAML}" ]]; then
  mapfile -t referenced_scripts < <(
    grep -oE '(\./)?scripts/[A-Za-z0-9._/-]+\.(sh|py)\b' "${CLOUDBUILD_YAML}" \
      | sed 's|^\./||' \
      | sort -u \
      || true
  )

  if [[ "${#referenced_scripts[@]}" -eq 0 ]]; then
    note "No scripts referenced from cloudbuild.yaml under scripts/"
  else
    echo "Referenced scripts in cloudbuild.yaml:"
    for p in "${referenced_scripts[@]}"; do
      echo " - ${p}"
      if [[ ! -f "${REPO_ROOT}/${p}" ]]; then
        err "cloudbuild.yaml references missing script: ${p}"
      fi
    done
  fi
fi

if [[ "${fail}" -ne 0 ]]; then
  echo "" >&2
  err "CI layout validation failed. Fix missing files/paths above."
  exit 1
fi

echo "OK: CI layout validation passed."
