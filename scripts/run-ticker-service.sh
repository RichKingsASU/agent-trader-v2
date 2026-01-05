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
LOCK_FILE="/tmp/run-ticker-service.pid"
if [ -e "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if ps -p "$PID" > /dev/null; then
        echo "Ticker service is already running with PID $PID. Exiting."
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
exec 1>>logs/ticker_service.log 2>&1

echo "[$(date -Iseconds)] Ticker service start (SYMBOLS=${TICKER_SYMBOLS:-AAPL,NVDA,TSLA})"
while true; do
  echo "[$(date -Iseconds)] tick: running ticker_service.py"
  
  if python -m functions.ticker_service; then
    echo "[$(date -Iseconds)] tick: ticker_service.py finished successfully"
  else
    exit_code=$?
    echo "[$(date -Iseconds)] ERROR: ticker_service.py exited with code $exit_code"
  fi
  
  echo "[$(date -Iseconds)] tick: sleeping for 10 seconds before retry"
  sleep 10
done
