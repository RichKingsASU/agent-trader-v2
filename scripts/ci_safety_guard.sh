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
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo /workspace)"
cd "$ROOT"

# --- Configuration ---
FAIL_FLAG=0
SUCCESS_COUNT=0
CHECK_COUNT=3

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
K8S_DIR="${REPO_ROOT}/k8s"
INFRA_DIR="${REPO_ROOT}/infra"

# --- Helper Functions ---
usage() {
    cat <<'EOF'
Usage: ci_safety_guard.sh [--dry-run] [--help]

Options:
  --dry-run   Run checks and print violations, but exit 0 (for local debugging).
  --help      Show this help text.
EOF
}

log() {
    # shellcheck disable=SC2145
    echo "$@"
}

fail() {
    local reason="$1"
    if [ "${DRY_RUN}" -eq 1 ]; then
        echo "DRY-RUN: would fail: ${reason}" >&2
        FAIL_FLAG=1
        return 0
    fi
    echo "ERROR: ${reason}" >&2
    exit 1
}

print_header() {
    echo "--- $1 ---"
}

print_success() {
    echo "PASSED: $1"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
}

print_failure() {
    local message="$1"
    local file="$2"
    local lines="$3"

    echo "FAILED: ${message}" >&2
    echo "  File: ${file}" >&2
    echo "  Match:" >&2
    echo "${lines}" >&2
    fail "${message} (${file})"
}

# --- Checks ---

# 1) Check for ':latest' image tags in K8s/infra manifests
check_for_latest_tag() {
    local rule_name="No ':latest' image tags"
    local remediation_hint="Pin images to an immutable tag (e.g. version or digest) instead of ':latest'."
    print_header "Checking for ':latest' image tags"
    local search_dirs=()
    [ -d "${K8S_DIR}" ] && search_dirs+=("${K8S_DIR}")
    [ -d "${INFRA_DIR}" ] && search_dirs+=("${INFRA_DIR}")

    local -a search_paths=()
    [[ -d "k8s" ]] && search_paths+=("k8s")
    [[ -d "infra" ]] && search_paths+=("infra")

    local found=0
    if [[ ${#search_paths[@]} -gt 0 ]]; then
        while IFS= read -r file; do
            [[ -z "${file}" ]] && continue
            while IFS= read -r match; do
                [[ -z "${match}" ]] && continue
                found=1
                local line_no="${match%%:*}"
                local line_text="${match#*:}"
                print_failure "${rule_name}" "${file}" "${line_no}" "${remediation_hint}" "${line_text}"
            done < <(grep -n "image:.*:latest" "${file}" 2>/dev/null || true)
        done < <(grep -r -l "image:.*:latest" "${search_paths[@]}" 2>/dev/null || true)
    fi

    local latest_files=""
    latest_files="$(grep -R -l -E "image:.*:latest" "${search_dirs[@]}" 2>/dev/null || true)"
    if [ -z "${latest_files}" ]; then
        print_success "No ':latest' image tags found."
        return 0
    fi

    while IFS= read -r file; do
        [ -z "${file}" ] && continue
        local lines=""
        lines="$(grep -n -E "image:.*:latest" "${file}" 2>/dev/null || true)"
        print_failure "Use of ':latest' image tag is forbidden." "${file}" "${lines}"
    done <<< "${latest_files}"
}

# 2) Check for AGENT_MODE set to EXECUTE
check_for_execute_mode() {
    local rule_name="No 'AGENT_MODE=EXECUTE' in committed code"
    local remediation_hint="Remove the setting or change to a safe mode (e.g. DRY_RUN/SIMULATE) and pass EXECUTE only via runtime config."
    print_header "Checking for 'AGENT_MODE=EXECUTE'"
    # Scan only manifest/config locations to avoid false positives in docs/tests/scripts.
    local scan_dirs=()
    [ -d "${K8S_DIR}" ] && scan_dirs+=("${K8S_DIR}")
    [ -d "${INFRA_DIR}" ] && scan_dirs+=("${INFRA_DIR}")
    [ -d "${REPO_ROOT}/config" ] && scan_dirs+=("${REPO_ROOT}/config")
    [ -d "${REPO_ROOT}/configs" ] && scan_dirs+=("${REPO_ROOT}/configs")

    if [ "${#scan_dirs[@]}" -eq 0 ]; then
        print_success "No manifest/config directories found; skipping AGENT_MODE scan."
        return 0
    fi

    local found=0
    # Exclude this script itself from the search
    while IFS= read -r file; do
        [[ -z "${file}" ]] && continue
        while IFS= read -r match; do
            [[ -z "${match}" ]] && continue
            found=1
            local line_no="${match%%:*}"
            local line_text="${match#*:}"
            print_failure "${rule_name}" "${file}" "${line_no}" "${remediation_hint}" "${line_text}"
        done < <(grep -n -i "AGENT_MODE.*EXECUTE" "${file}" 2>/dev/null || true)
    done < <(grep -r -i -l "AGENT_MODE.*EXECUTE" "." --exclude-dir=".git" --exclude="ci_safety_guard.sh" 2>/dev/null || true)

    if [[ "${found}" -eq 0 ]]; then
        print_success "No instances of 'AGENT_MODE=EXECUTE' found."
        return 0
    fi

    while IFS= read -r file; do
        [ -z "${file}" ] && continue
        local lines=""
        lines="$(grep -n -i -E "AGENT_MODE[[:space:]]*[:=][[:space:]]*EXECUTE" "${file}" 2>/dev/null || true)"
        print_failure "'AGENT_MODE' must not be set to 'EXECUTE' in committed manifests/config." "${file}" "${lines}"
    done <<< "${execute_files}"
}

# 3) Check for execution agent replicas > 0
check_for_scaled_executors() {
    local rule_name="Execution agent replicas must be 0"
    local remediation_hint="Set replicas to 0 in committed manifests; scale via runtime tooling (e.g. HPA/override) when needed."
    print_header "Checking for scaled execution agents (replicas > 0)"
    if [ ! -d "${K8S_DIR}" ]; then
        print_success "No k8s/ directory found; skipping executor replica scan."
        return 0
    fi

    # Find files that look like executor manifests, then check replicas
    if [[ -d "k8s" ]]; then
        while IFS= read -r -d '' file; do
            # This grep pattern finds "replicas:" followed by any number (not zero)
            if grep -q "replicas: *[1-9]" "${file}" 2>/dev/null; then
                while IFS= read -r match; do
                    [[ -z "${match}" ]] && continue
                    found_scaled=1
                    local line_no="${match%%:*}"
                    local line_text="${match#*:}"
                    print_failure "${rule_name}" "${file}" "${line_no}" "${remediation_hint}" "${line_text}"
                done < <(grep -n "replicas: *[1-9]" "${file}" 2>/dev/null || true)
            fi
        done < <(find "k8s" -type f \( -name "*-executor.yaml" -o -name "*-trader.yaml" \) -print0 2>/dev/null || true)
    fi

    if [ -z "${execution_manifests}" ]; then
        print_success "No executor/trader manifests found; skipping replica check."
        return 0
    fi

    while IFS= read -r file; do
        [ -z "${file}" ] && continue
        # This grep pattern finds "replicas:" followed by any number (not zero)
        if grep -q -E "replicas:[[:space:]]*[1-9]" "${file}" 2>/dev/null; then
            local lines=""
            lines="$(grep -n -E "replicas:[[:space:]]*[1-9]" "${file}" 2>/dev/null || true)"
            print_failure "Execution agent replicas must be 0 in committed code." "${file}" "${lines}"
        fi
    done <<< "${execution_manifests}"

    print_success "No execution agents found with replicas > 0."
}

# --- Main Execution ---
echo "Running AgentTrader v2 CI Safety Guard..."
echo "Repo root: ${ROOT}"
echo ""

check_for_latest_tag
echo ""
check_for_execute_mode
echo ""
check_for_scaled_executors
echo ""

# --- Final Result ---
print_header "Result"
if [[ "$FAIL_FLAG" -ne 0 ]]; then
    echo "🔴 Safety guard failed. Found critical violations."
    echo "   Please review the errors above and correct the identified files."
    exit 1
else
    if [[ "$SUCCESS_COUNT" -eq "$CHECK_COUNT" ]]; then
        echo "🟢 All $CHECK_COUNT safety checks passed successfully."
        echo "CI SAFETY GUARD PASSED"
        exit 0
    else
        echo "🟡 Warning: Not all checks passed, but no failures detected. Please review output."
        exit 1 # Fail safe if success count doesn't match
    fi

    echo "SUCCESS: All ${CHECK_COUNT} safety checks passed."
}

main "$@"
