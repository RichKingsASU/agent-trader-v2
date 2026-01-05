#!/usr/bin/env bash
set -euo pipefail

# Kill any existing uvicorn processes so ports 8001/8002 are free (best-effort)
pkill -f "uvicorn" 2>/dev/null || true

# NOTE:
# - Do not hardcode secrets here.
# - Provide required env vars via your shell or a local .env file (not committed).

# Strategy on 8001
uvicorn backend.strategy_service.app:app --host 0.0.0.0 --port 8001 &
STRAT_PID=$!

# Risk on 8002
uvicorn backend.risk_service.app:app --host 0.0.0.0 --port 8002 &
RISK_PID=$!

echo "Strategy service PID: $STRAT_PID"
echo "Risk service PID: $RISK_PID"

trap "echo 'Stopping...'; kill $STRAT_PID $RISK_PID 2>/dev/null || true" SIGINT SIGTERM

wait
