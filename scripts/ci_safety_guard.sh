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
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "${REPO_ROOT}" ]]; then
    if [[ -d "/workspace" ]]; then
        REPO_ROOT="/workspace"
    else
        # Fallback for environments without git + /workspace (best-effort).
        REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
    fi
fi

# --- Configuration ---
FAIL_FLAG=0
SUCCESS_COUNT=0
CHECK_COUNT=3

# --- Helper Functions ---
print_header() {
    echo "--- $1 ---"
}

print_success() {
    echo "✅ PASSED: $1"
    SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
}

print_failure() {
    # Args: rule_name file line remediation_hint [match_text]
    local rule_name="$1"
    local file="$2"
    local line="$3"
    local remediation_hint="$4"
    local match_text="${5:-}"

    echo "❌ FAILED: ${rule_name}"
    echo "   Location: ${file}:${line}"
    if [[ -n "${match_text}" ]]; then
        echo "   Match: ${match_text}"
    fi
    echo "   Remediation: ${remediation_hint}"
    FAIL_FLAG=1
}

# --- Checks ---

# 1) Check for ':latest' image tags in K8s/infra manifests
check_for_latest_tag() {
    local rule_name="No ':latest' image tags"
    local remediation_hint="Pin images to an immutable tag (e.g. version or digest) instead of ':latest'."
    print_header "Checking for ':latest' image tags"

    local -a search_paths=()
    [[ -d "${REPO_ROOT}/k8s" ]] && search_paths+=("${REPO_ROOT}/k8s")
    [[ -d "${REPO_ROOT}/infra" ]] && search_paths+=("${REPO_ROOT}/infra")

    local found=0
    if [[ ${#search_paths[@]} -gt 0 ]]; then
        while IFS= read -r file; do
            [[ -z "${file}" ]] && continue
            while IFS= read -r match; do
                [[ -z "${match}" ]] && continue
                found=1
                local line_no="${match%%:*}"
                local line_text="${match#*:}"
                local rel_file="${file#${REPO_ROOT}/}"
                print_failure "${rule_name}" "${rel_file}" "${line_no}" "${remediation_hint}" "${line_text}"
            done < <(grep -n "image:.*:latest" "${file}" 2>/dev/null || true)
        done < <(grep -r -l "image:.*:latest" "${search_paths[@]}" 2>/dev/null || true)
    fi

    if [[ "${found}" -eq 0 ]]; then
        print_success "No ':latest' image tags found."
    fi
}

# 2) Check for AGENT_MODE set to EXECUTE
check_for_execute_mode() {
    local rule_name="No 'AGENT_MODE=EXECUTE' in committed code"
    local remediation_hint="Remove the setting or change to a safe mode (e.g. DRY_RUN/SIMULATE) and pass EXECUTE only via runtime config."
    print_header "Checking for 'AGENT_MODE=EXECUTE'"

    local found=0
    # Exclude this script itself from the search
    while IFS= read -r file; do
        [[ -z "${file}" ]] && continue
        while IFS= read -r match; do
            [[ -z "${match}" ]] && continue
            found=1
            local line_no="${match%%:*}"
            local line_text="${match#*:}"
            local rel_file="${file#${REPO_ROOT}/}"
            print_failure "${rule_name}" "${rel_file}" "${line_no}" "${remediation_hint}" "${line_text}"
        done < <(grep -n -i "AGENT_MODE.*EXECUTE" "${file}" 2>/dev/null || true)
    done < <(grep -r -i -l "AGENT_MODE.*EXECUTE" "${REPO_ROOT}" --exclude="ci_safety_guard.sh" 2>/dev/null || true)

    if [[ "${found}" -eq 0 ]]; then
        print_success "No instances of 'AGENT_MODE=EXECUTE' found."
    fi
}

# 3) Check for execution agent replicas > 0
check_for_scaled_executors() {
    local rule_name="Execution agent replicas must be 0"
    local remediation_hint="Set replicas to 0 in committed manifests; scale via runtime tooling (e.g. HPA/override) when needed."
    print_header "Checking for scaled execution agents (replicas > 0)"

    local found_scaled=0
    # Find files that look like executor manifests, then check replicas
    if [[ -d "${REPO_ROOT}/k8s" ]]; then
        while IFS= read -r -d '' file; do
            # This grep pattern finds "replicas:" followed by any number (not zero)
            if grep -q "replicas: *[1-9]" "${file}" 2>/dev/null; then
                while IFS= read -r match; do
                    [[ -z "${match}" ]] && continue
                    found_scaled=1
                    local line_no="${match%%:*}"
                    local line_text="${match#*:}"
                    local rel_file="${file#${REPO_ROOT}/}"
                    print_failure "${rule_name}" "${rel_file}" "${line_no}" "${remediation_hint}" "${line_text}"
                done < <(grep -n "replicas: *[1-9]" "${file}" 2>/dev/null || true)
            fi
        done < <(find "${REPO_ROOT}/k8s" -type f \( -name "*-executor.yaml" -o -name "*-trader.yaml" \) -print0 2>/dev/null || true)
    fi

    if [[ "${found_scaled}" -eq 0 ]]; then
        print_success "No execution agents found with replicas > 0."
    fi
}

# --- Main Execution ---
echo "Running AgentTrader v2 CI Safety Guard..."
echo "Repo root: ${REPO_ROOT}"
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
fi
