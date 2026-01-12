#!/usr/bin/env bash
#
# Authoritative pre-deployment safety gate (CI + local).
#
# Single source of truth for deploy safety. This script is intentionally
# fail-fast and must never silently skip safety logic.
#
# Guarantees:
# - Fails on dependency integrity issues
# - Fails on unit test failures
# - Fails on safety verifier failures
#
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo /workspace)"
cd "${REPO_ROOT}"

INNER_MODE="${1:-}"

# Required CI environment defaults (do not override if already set).
: "${TRADING_MODE:=paper}"
: "${AGENT_MODE:=OFF}"

echo "== pre_deployment_gate =="
echo "repo_root:    ${REPO_ROOT}"
echo "trading_mode: ${TRADING_MODE}"
echo "agent_mode:   ${AGENT_MODE}"
echo ""

# If Firestore emulator isn't already active, run the full gate under
# `firebase-tools emulators:exec` so safety verifiers can run without
# production secrets.
#
# NOTE: We intentionally do this *inside* the gate so CI can call a single
# command: `./scripts/pre_deployment_gate.sh`.
if [[ "${INNER_MODE}" != "--inner" ]] && [[ -z "${FIRESTORE_EMULATOR_HOST:-}" ]]; then
  if command -v npx >/dev/null 2>&1; then
    echo "Starting ephemeral Firestore emulator for safety gates..."
    echo ""
    exec npx -y firebase-tools@latest emulators:exec \
      --only firestore \
      --project "${GOOGLE_CLOUD_PROJECT:-demo-agenttrader-ci}" \
      "./scripts/pre_deployment_gate.sh --inner"
  fi

  echo "ERROR: FIRESTORE_EMULATOR_HOST is not set and 'npx' is unavailable." >&2
  echo "Install Node/npm (for firebase-tools) or set FIRESTORE_EMULATOR_HOST to run this gate." >&2
  exit 2
fi

echo "--- dependency integrity ---"
python -m pip --version
python -m pip check
echo ""

echo "--- safety verifiers ---"
python ./scripts/verify_zero_trust.py
python ./scripts/verify_risk_management.py
echo ""

echo "--- unit tests (deterministic) ---"
pytest
echo ""

echo "PASS: pre_deployment_gate"

