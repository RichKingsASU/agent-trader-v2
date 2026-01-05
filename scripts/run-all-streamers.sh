#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Source environment to read feature flags
if [ -f ".env.local" ]; then
    set -a
    # shellcheck disable=SC1091
    source .env.local
    set +a
fi

# --- Conditional Streamer Execution ---

if [[ "${ENABLE_ALPACA:-0}" == "1" ]]; then
    echo "Starting Alpaca streamer..."
    ./scripts/run-alpaca-quotes-stream.sh 2>&1 | tee logs/alpaca_stream.log &
    echo "  - Alpaca streamer PID: $!"
else
    echo "Alpaca streamer disabled by feature flag."
fi

echo "Streamer startup sequence complete."
