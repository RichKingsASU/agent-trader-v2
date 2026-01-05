#!/usr/bin/env bash
set -euo pipefail

# Ensure we are in the project root
cd "$(dirname "$0")/../" || exit 1

# --- Source Environment Variables ---
if [ -f ".env.local" ]; then
    echo "Sourcing environment variables from .env.local"
    set -a
    # shellcheck disable=SC1091
    source .env.local
    set +a
fi
# --- End Source ---

# --- PID Lock Guard ---
LOCK_FILE="/tmp/run-alpaca-quotes-stream.pid"
if [ -e "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null; then
        echo "Quote streamer is already running with PID $PID. Exiting."
        exit 1
    else
        echo "Stale lock file found for PID $PID. Removing."
        rm -f "$LOCK_FILE"
    fi
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT
# --- End Lock Guard ---

mkdir -p logs
exec 1>>logs/alpaca_quotes_stream.log 2>&1

echo "[$(date -Iseconds)] stream start (SYMS=${ALPACA_SYMBOLS:-unset})"
while true; do
  echo "[$(date -Iseconds)] tick: running alpaca_streamer.py"
  
  if python -m streams.alpaca_streamer; then
    echo "[$(date -Iseconds)] tick: alpaca_streamer.py finished successfully"
  else
    exit_code=$?
    echo "[$(date -Iseconds)] ERROR: alpaca_streamer.py exited with code $exit_code"
  fi
  
  echo "[$(date -Iseconds)] tick: sleeping for 5 seconds before retry"
  sleep 5
done
