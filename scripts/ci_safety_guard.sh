#!/bin/sh
#
# CI Safety Guard for AgentTrader v2
#
# This script is a read-only, non-destructive CI check that enforces critical
# safety and operational standards. It fails the build if any of the following
# high-risk conditions are detected in the codebase.
#
# It does NOT change runtime behavior or add any dependencies.

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
    echo "❌ FAILED: $1"
    echo "   File: $2"
    echo "   Line: $3"
    FAIL_FLAG=1
}

# --- Checks ---

# 1) Check for ':latest' image tags in K8s/infra manifests
check_for_latest_tag() {
    print_header "Checking for ':latest' image tags"
    LATEST_FILES=$(grep -r -l "image:.*:latest" ./k8s ./infra 2>/dev/null)
    if [ -n "$LATEST_FILES" ]; then
        for FILE in $LATEST_FILES; do
            LINES=$(grep -n "image:.*:latest" "$FILE")
            print_failure "Use of ':latest' image tag is forbidden." "$FILE" "$LINES"
        done
    else
        print_success "No ':latest' image tags found."
    fi
}

# 2) Check for AGENT_MODE set to EXECUTE
check_for_execute_mode() {
    print_header "Checking for 'AGENT_MODE=EXECUTE'"
    # Exclude this script itself from the search
    EXECUTE_FILES=$(grep -r -i -l "AGENT_MODE.*EXECUTE" . --exclude="ci_safety_guard.sh" 2>/dev/null)
    if [ -n "$EXECUTE_FILES" ]; then
        for FILE in $EXECUTE_FILES; do
            LINES=$(grep -n -i "AGENT_MODE.*EXECUTE" "$FILE")
            print_failure "'AGENT_MODE' must not be set to 'EXECUTE' in committed code." "$FILE" "$LINES"
        done
    else
        print_success "No instances of 'AGENT_MODE=EXECUTE' found."
    fi
}

# 3) Check for execution agent replicas > 0
check_for_scaled_executors() {
    print_header "Checking for scaled execution agents (replicas > 0)"
    # Find files that look like executor manifests, then check replicas
    EXECUTION_MANIFESTS=$(find ./k8s -type f \( -name "*-executor.yaml" -o -name "*-trader.yaml" \))
    FOUND_SCALED_EXECUTOR=0
    if [ -n "$EXECUTION_MANIFESTS" ]; then
        for FILE in $EXECUTION_MANIFESTS; do
            # This grep pattern finds "replicas:" followed by any number (not zero)
            if grep -q "replicas: *[1-9]" "$FILE"; then
                LINES=$(grep -n "replicas: *[1-9]" "$FILE")
                print_failure "Execution agent replicas must be 0 in committed code." "$FILE" "$LINES"
                FOUND_SCALED_EXECUTOR=1
            fi
        done
    fi

    if [ "$FOUND_SCALED_EXECUTOR" -eq 0 ]; then
        print_success "No execution agents found with replicas > 0."
    fi
}

# --- Main Execution ---
echo "Running AgentTrader v2 CI Safety Guard..."
echo ""

check_for_latest_tag
echo ""
check_for_execute_mode
echo ""
check_for_scaled_executors
echo ""

# --- Final Result ---
print_header "Result"
if [ "$FAIL_FLAG" -ne 0 ]; then
    echo "🔴 Safety guard failed. Found critical violations."
    echo "   Please review the errors above and correct the identified files."
    exit 1
else
    if [ "$SUCCESS_COUNT" -eq "$CHECK_COUNT" ]; then
        echo "🟢 All $CHECK_COUNT safety checks passed successfully."
        exit 0
    else
        echo "🟡 Warning: Not all checks passed, but no failures detected. Please review output."
        exit 1 # Fail safe if success count doesn't match
    fi
fi
