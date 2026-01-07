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

# --- Configuration / Globals ---
DRY_RUN=0
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

    if [ "${#search_dirs[@]}" -eq 0 ]; then
        print_success "No k8s/ or infra/ directory found; skipping ':latest' scan."
        return 0
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

    # Look for explicit assignment forms: AGENT_MODE=EXECUTE or AGENT_MODE: EXECUTE
    local execute_files=""
    execute_files="$(grep -R -i -l -E "AGENT_MODE[[:space:]]*[:=][[:space:]]*EXECUTE" "${scan_dirs[@]}" 2>/dev/null || true)"

    if [ -z "${execute_files}" ]; then
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
    local execution_manifests=""
    execution_manifests="$(find "${K8S_DIR}" -type f \( -name "*-executor.yaml" -o -name "*-trader.yaml" \) 2>/dev/null || true)"

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
main() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --dry-run)
                DRY_RUN=1
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                echo "ERROR: Unknown argument: $1" >&2
                usage >&2
                exit 2
                ;;
        esac
    done

    log "Running AgentTrader v2 CI Safety Guard..."
    log "Repo root: ${REPO_ROOT}"
    if [ "${DRY_RUN}" -eq 1 ]; then
        log "Mode: DRY-RUN (will not fail the build)"
    fi
    log ""

    check_for_latest_tag
    log ""
    check_for_execute_mode
    log ""
    check_for_scaled_executors
    log ""

    # --- Final Result ---
    print_header "Result"
    if [ "${FAIL_FLAG}" -ne 0 ]; then
        if [ "${DRY_RUN}" -eq 1 ]; then
            echo "DRY-RUN COMPLETE: Violations were detected (see above), but exiting 0 by request."
            exit 0
        fi
        echo "Safety guard failed: critical violations detected." >&2
        exit 1
    fi

    if [ "${SUCCESS_COUNT}" -ne "${CHECK_COUNT}" ]; then
        # Fail safe if the expected number of checks didn't report success.
        fail "Internal error: expected ${CHECK_COUNT} checks to pass, got ${SUCCESS_COUNT}."
    fi

    echo "SUCCESS: All ${CHECK_COUNT} safety checks passed."
}

main "$@"
