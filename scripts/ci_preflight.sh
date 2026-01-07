#!/usr/bin/env bash
#
# CI Preflight Validator (Cloud Build)
#
# Goals (fail fast before Cloud Build runs expensive steps):
# - cloudbuild YAML schema sanity (lightweight)
# - all referenced scripts exist
# - all user-defined substitutions start with "_"
# - no ":latest" image tags
# - no AGENT_MODE=EXECUTE
#
# Constraints: Bash only; no external dependencies like yq/python.
#
set -euo pipefail

ROOT="$(
  git rev-parse --show-toplevel 2>/dev/null || pwd
)"
cd "${ROOT}"

err() { echo "ERROR: $*" >&2; }
note() { echo "INFO: $*" >&2; }

fail=0

is_file() {
  [[ -f "$1" ]]
}

add_error() {
  err "$*"
  fail=1
}

dedupe_list() {
  # Reads newline-delimited strings on stdin; prints unique values.
  awk 'NF { if (!seen[$0]++) print $0 }'
}

yaml_without_block_scalars() {
  # Prints YAML with block scalar *bodies* removed (keeps headers).
  #
  # This is intentionally lightweight (not a full YAML parser). It’s used to
  # avoid treating embedded bash scripts (| / > blocks) as Cloud Build YAML
  # fields for the purpose of substitution/env checks.
  awk '
    function indent(s) { match(s, /^[ \t]*/); return RLENGTH }
    BEGIN { in_scalar=0; scalar_indent=0 }
    {
      if (in_scalar == 1) {
        # End scalar block when indentation decreases back to header level.
        if (indent($0) <= scalar_indent && $0 !~ /^[ \t]*$/) {
          in_scalar=0
        } else {
          next
        }
      }

      # Detect scalar header lines:
      #   key: |
      #   - |
      if ($0 ~ /^[ \t]*-[ \t]*[|>][-+]?([ \t]*($|#.*))$/ ||
          $0 ~ /^[ \t]*[A-Za-z0-9_.-]+:[ \t]*[|>][-+]?([ \t]*($|#.*))$/) {
        scalar_indent = indent($0)
        in_scalar=1
        print $0
        next
      }

      print $0
    }
  ' "$1"
}

discover_cloudbuild_files() {
  local -a candidates=()
  shopt -s nullglob
  candidates+=(cloudbuild.yaml cloudbuild.yml cloudbuild.*.yaml cloudbuild.*.yml)
  candidates+=(infra/cloudbuild*.yaml infra/cloudbuild*.yml)
  shopt -u nullglob

  printf "%s\n" "${candidates[@]}" | dedupe_list
}

require_at_least_one_cloudbuild() {
  local found=0
  while IFS= read -r f; do
    [[ -z "${f}" ]] && continue
    if is_file "${f}"; then
      found=1
      break
    fi
  done <<<"$(discover_cloudbuild_files)"

  if [[ "${found}" -ne 1 ]]; then
    add_error "no Cloud Build config files found (expected at least ./cloudbuild.yaml)"
  fi
}

validate_yaml_sanity() {
  local f="$1"

  if [[ ! -s "${f}" ]]; then
    add_error "${f}: file missing or empty"
    return 0
  fi

  # Tabs are a common cause of YAML breakage (and are invalid indentation in YAML).
  if awk 'index($0, "\t") > 0 { print NR ":" $0 }' "${f}" | sed -n '1,20p' | grep -q .; then
    add_error "${f}: contains TAB characters (YAML indentation must use spaces)"
  fi

  # Minimal Cloud Build schema sanity:
  # - must define steps:
  # - must have at least one step item with a name
  if ! grep -qE '^[[:space:]]*steps:[[:space:]]*($|#)' "${f}"; then
    add_error "${f}: missing required top-level key 'steps:'"
    return 0
  fi

  if ! grep -qE '^[[:space:]]*-[[:space:]]*name:[[:space:]]*' "${f}"; then
    add_error "${f}: no steps found with '- name:' (invalid Cloud Build steps list?)"
  fi
}

extract_referenced_scripts() {
  local f="$1"

  # Extract script-like paths under scripts/ referenced in the YAML.
  # This intentionally scopes to scripts/ to avoid false positives.
  # Examples matched:
  #   bash ./scripts/foo.sh
  #   ./scripts/foo.py
  #   "scripts/foo.sh"
  grep -oE '(\./)?scripts/[A-Za-z0-9._/-]+\.(sh|py)\b' "${f}" \
    | sed 's|^\./||' \
    | dedupe_list \
    || true
}

validate_referenced_scripts_exist() {
  local f="$1"

  local any=0
  while IFS= read -r rel; do
    [[ -z "${rel}" ]] && continue
    any=1
    if [[ ! -f "${ROOT}/${rel}" ]]; then
      add_error "${f}: references missing script: ${rel}"
    fi
  done <<<"$(extract_referenced_scripts "${f}")"

  if [[ "${any}" -eq 0 ]]; then
    note "${f}: no scripts referenced under scripts/ (skipping script existence checks)"
  fi
}

validate_substitutions_underscore_keys() {
  local f="$1"

  # Enforce that *user-defined* substitutions declared under "substitutions:" start with "_".
  # This is a lightweight YAML block scan (no full YAML parsing).
  local bad_keys
  bad_keys="$(
    awk '
      function ltrim(s) { sub(/^[ \t]+/, "", s); return s }
      function indent(s) { match(s, /^[ \t]*/); return RLENGTH }
      /^[ \t]*substitutions:[ \t]*($|#)/ { in_block=1; base=indent($0); next }
      in_block==1 {
        if ($0 ~ /^[ \t]*$/) next
        if ($0 ~ /^[ \t]*#/) next
        if (indent($0) <= base) { in_block=0; next }
        line=ltrim($0)
        # capture "KEY:" at start of mapping line
        if (match(line, /^[A-Za-z0-9][A-Za-z0-9_]*[ \t]*:/)) {
          key=substr(line, 1, index(line, ":")-1)
          gsub(/[ \t]+/, "", key)
          if (key !~ /^_/) print key
        }
      }
    ' "${f}" | dedupe_list
  )"

  if [[ -n "${bad_keys}" ]]; then
    while IFS= read -r k; do
      [[ -z "${k}" ]] && continue
      add_error "${f}: substitution key does not start with '_': ${k}"
    done <<<"${bad_keys}"
  fi
}

validate_substitution_references() {
  local f="$1"

  # Enforce that any ${VAR} references are either:
  # - Cloud Build built-ins (allowlisted), or
  # - user-defined substitutions that start with "_"
  #
  # NOTE: We only scan ${...} patterns to avoid false positives inside shell
  # scripts (e.g., $1, $PATH, etc.).
  local allow_re
  allow_re='^(PROJECT_ID|BUILD_ID|REPO_NAME|BRANCH_NAME|TAG_NAME|REVISION_ID|COMMIT_SHA|SHORT_SHA|LOCATION|TRIGGER_NAME|TRIGGER_ID)$'

  local vars
  vars="$(
    # Exclude scalar bodies (embedded scripts) and comment-only lines.
    yaml_without_block_scalars "${f}" \
      | grep -vE '^[[:space:]]*#' \
      | grep -oE '\$\{[A-Za-z][A-Za-z0-9_]*\}' \
      | sed -E 's/^\$\{|\}$//g' \
      | dedupe_list \
      || true
  )"

  if [[ -z "${vars}" ]]; then
    return 0
  fi

  while IFS= read -r v; do
    [[ -z "${v}" ]] && continue
    if [[ "${v}" =~ ${allow_re} ]]; then
      continue
    fi
    if [[ "${v}" != _* ]]; then
      add_error "${f}: substitution reference must start with '_' (or be a built-in): \${${v}}"
    fi
  done <<<"${vars}"
}

validate_no_latest_images() {
  local f="$1"

  # Disallow explicit ":latest" tags in Cloud Build YAML.
  # Allow Secret Manager "latest" versions in CLI flags, e.g.:
  #   --update-secrets=FOO=bar:latest
  #   --set-secrets=FOO=bar:latest
  local hits
  hits="$(
    yaml_without_block_scalars "${f}" \
      | awk '
          /^[ \t]*#/ { next }
          /:latest([^A-Za-z0-9_]|$)/ {
            if ($0 ~ /--(update|set)-secrets=[^[:space:]]+:latest([^A-Za-z0-9_]|$)/) next
            print NR ":" $0
          }
        ' \
      | sed -n '1,50p'
  )"

  if [[ -n "${hits}" ]]; then
    add_error "${f}: contains forbidden ':latest' tag(s) (first matches):"
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      err "  ${line}"
    done <<<"${hits}"
  fi
}

validate_no_agent_mode_execute() {
  local f="$1"

  local hits
  hits="$(
    yaml_without_block_scalars "${f}" \
      | awk '
          /^[ \t]*#/ { next }
          {
            l=tolower($0)
            # Match YAML env-style settings, e.g.:
            #   - AGENT_MODE=EXECUTE
            #   - "AGENT_MODE=EXECUTE"
            #   AGENT_MODE: EXECUTE
            if (l ~ /agent_mode[ \t]*[:=][ \t]*["\047]?execute["\047]?/) {
              print NR ":" $0
            }
          }
        ' \
      | sed -n '1,50p'
  )"

  if [[ -n "${hits}" ]]; then
    add_error "${f}: contains forbidden AGENT_MODE=EXECUTE (first matches):"
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      err "  ${line}"
    done <<<"${hits}"
  fi
}

main() {
  local -a files=()
  if [[ "$#" -gt 0 ]]; then
    files=("$@")
  else
    mapfile -t files < <(discover_cloudbuild_files)
  fi

require_at_least_one_cloudbuild

local validated_any=0
for f in "${files[@]}"; do
  [[ -z "${f}" ]] && continue
  [[ ! -f "${f}" ]] && continue
  validated_any=1

  note "Validating ${f}"
  validate_yaml_sanity "${f}"
  validate_referenced_scripts_exist "${f}"
  validate_substitutions_underscore_keys "${f}"
  validate_substitution_references "${f}"
  validate_no_latest_images "${f}"
  validate_no_agent_mode_execute "${f}"
done

if [[ "${validated_any}" -eq 0 ]]; then
  add_error "no Cloud Build config files exist at discovered paths"
fi

if [[ "${fail}" -ne 0 ]]; then
  err "CI preflight failed."
  exit 1
fi

echo "OK: CI preflight passed."
}

main "$@"
