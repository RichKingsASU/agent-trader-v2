#!/usr/bin/env bash
#
# CI Safety Guard for AgentTrader v2
#
# This script is a read-only, non-destructive CI check that enforces critical
# safety and operational standards. It fails the build if any of the following
# high-risk conditions are detected in the codebase.
#
# It does NOT change runtime behavior or add any dependencies.

set -euo pipefail

# --- Repo Root (run from any working directory) ---
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo /workspace)"
cd "${REPO_ROOT}"

DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: scripts/ci_safety_guard.sh [--dry-run] [--help]

Options:
  --dry-run   Print violations but exit 0 (local debugging).
  --help      Show this help text.
EOF
}

fatal() {
  echo "ERROR: $*" >&2
  exit 2
}

fail() {
  local msg="$1"
  if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "DRY-RUN: would fail: ${msg}" >&2
    return 0
  fi
  echo "❌ FAILED: ${msg}" >&2
  exit 1
}

header() {
  echo "--- $1 ---"
}

pass() {
  echo "✅ PASSED: $1"
}

# Run grep against an explicit file list, interpreting exit codes robustly:
# - 0 => policy violation (FAIL)
# - 1 => PASS (no matches)
# - 2 => grep/runtime error (FAIL; print diagnostics)
run_grep_check() {
  local check_name="$1"
  local fail_message="$2"
  local grep_pattern="$3"
  shift 3
  local -a files=( "$@" )

  header "${check_name}"
  echo "Files scanned: ${#files[@]}"
  if ((${#files[@]} == 0)); then
    pass "No files to scan."
    return 0
  fi

  set +e
  local out
  out="$(grep -nH -E "${grep_pattern}" -- "${files[@]}" 2>&1)"
  local rc=$?
  set -e

  if [[ ${rc} -eq 0 ]]; then
    echo "${out}" >&2
    fail "${fail_message}"
  elif [[ ${rc} -eq 1 ]]; then
    pass "No matches found."
    return 0
  else
    echo "${out}" >&2
    fail "grep error while running: ${check_name}"
  fi
}

list_files() {
  local root="$1"
  shift
  local -a find_args=( "$@" )
  if [[ ! -d "${root}" ]]; then
    return 0
  fi
  # shellcheck disable=SC2016
  find "${root}" "${find_args[@]}" -print0
}

main() {
  while (($#)); do
    case "$1" in
      --dry-run) DRY_RUN=1 ;;
      --help|-h) usage; exit 0 ;;
      *) fatal "unknown arg: $1" ;;
    esac
    shift
  done

  echo "Running AgentTrader v2 CI Safety Guard..."
  echo "Repo root: ${REPO_ROOT}"

  # Script inventory/risk policy must run first (fast fail).
  PY_BIN=""
  if command -v python3 >/dev/null 2>&1; then
    PY_BIN="python3"
  elif command -v python >/dev/null 2>&1; then
    PY_BIN="python"
  else
    fail "python is required to run scripts/ci/enforce_script_risk_policy.py"
  fi
  "${PY_BIN}" "${REPO_ROOT}/scripts/ci/enforce_script_risk_policy.py"

  # 1) No ':latest' image tags in YAML (exclude cloudbuild yamls)
  local -a yaml_files=()
  mapfile -d '' -t yaml_files < <(
    find "${REPO_ROOT}" -type f \( -name "*.yaml" -o -name "*.yml" \) \
      -not -path "*/.git/*" \
      -not -name "cloudbuild*.yaml" \
      -not -name "cloudbuild*.yml" \
      -print0
  )
  run_grep_check \
    "Rule: forbid ':latest' image tags" \
    "Use of ':latest' image tag is forbidden (pin to immutable tag or digest)." \
    '^[[:space:]]*image:[[:space:]]*[^#[:space:]]+:latest([[:space:]]|$)' \
    "${yaml_files[@]}"

  # 2) No AGENT_MODE=EXECUTE in committed manifests/config
  local -a scan_dirs=()
  [[ -d "${REPO_ROOT}/k8s" ]] && scan_dirs+=("${REPO_ROOT}/k8s")
  [[ -d "${REPO_ROOT}/infra" ]] && scan_dirs+=("${REPO_ROOT}/infra")
  [[ -d "${REPO_ROOT}/config" ]] && scan_dirs+=("${REPO_ROOT}/config")
  [[ -d "${REPO_ROOT}/configs" ]] && scan_dirs+=("${REPO_ROOT}/configs")

  local -a config_files=()
  if ((${#scan_dirs[@]} > 0)); then
    mapfile -d '' -t config_files < <(
      find "${scan_dirs[@]}" -type f \
        \( -name "*.yaml" -o -name "*.yml" -o -name "*.env" -o -name "*.sh" -o -name "*.py" -o -name "Dockerfile" \) \
        -not -path "*/.git/*" \
        -not -name "cloudbuild*.yaml" \
        -not -name "cloudbuild*.yml" \
        -print0
    )
  fi
  run_grep_check \
    "Rule: forbid AGENT_MODE=EXECUTE" \
    "AGENT_MODE must not be set to EXECUTE in committed manifests/config." \
    'AGENT_MODE[[:space:]]*[:=][[:space:]]*["'\'']?EXECUTE["'\'']?' \
    "${config_files[@]}"

  # 3) Execution agent must not be scaled in committed manifests (replicas > 0)
  local -a execution_agent_manifests=()
  if [[ -d "${REPO_ROOT}/k8s" ]]; then
    while IFS= read -r -d '' f; do
      case "${f}" in
        *execution-agent*|*execution_agent*)
          execution_agent_manifests+=( "${f}" )
          ;;
      esac
    done < <(
      find "${REPO_ROOT}/k8s" -type f \( -name "*.yaml" -o -name "*.yml" \) \
        -not -path "*/.git/*" \
        -print0
    )
  fi
  run_grep_check \
    "Rule: forbid scaled execution-agent replicas" \
    "Execution agent replicas must be 0 in committed manifests." \
    '^[[:space:]]*replicas:[[:space:]]*[1-9]' \
    "${execution_agent_manifests[@]}"

  header "Result"
  pass "CI safety guard passed."
}

main "$@"
