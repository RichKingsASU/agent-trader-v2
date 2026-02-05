#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Load backend env if it exists
if [[ -f "$ROOT_DIR/backend/.env" ]]; then
  echo "Sourcing backend/.env"
  set -a
  source "$ROOT_DIR/backend/.env"
  set +a
fi

# Ensure required env vars are present or warn
if [[ -z "${APCA_API_KEY_ID:-}" ]]; then
  echo "WARNING: APCA_API_KEY_ID is not set. Data ingestion will likely fail."
fi

echo "Starting Market Data Ingestion Streamer..."
echo "Symbols: ${ALPACA_SYMBOLS:-SPY,QQQ,IWM}"
echo "Feed: ${ALPACA_DATA_FEED:-iex}"

# Run the market data MCP server (which contains the streamer)
if [[ -f "$ROOT_DIR/.venv/bin/python3" ]]; then
    "$ROOT_DIR/.venv/bin/python3" -m uvicorn backend.app:app --host 0.0.0.0 --port 8081 --reload
else
    python3 -m uvicorn backend.app:app --host 0.0.0.0 --port 8081 --reload
fi
