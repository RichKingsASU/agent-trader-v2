
#!/usr/bin/env bash
set -euo pipefail

if [ -f "agenttrader/.env.local" ]; then
    echo "Sourcing environment variables from .env.local"
    set -a
    source agenttrader/.env.local
    set +a
fi

LOG_FILE=$(mktemp)

(echo "LISTEN live_quotes_change;"; cat) | psql -v VERBOSITY=verbose "$DATABASE_URL" > "$LOG_FILE" &
LISTENER_PID=$!

sleep 2

python agenttrader/backend/streams/test_live_quote_ingest.py

sleep 2

kill $LISTENER_PID

if grep -q "{" "$LOG_FILE"; then
    echo "Test successful: Notification received."
    rm "$LOG_FILE"
    mv agenttrader/.env.local.bak agenttrader/.env.local
else
    echo "Test failed: No notification received."
    echo "--- Log File ---"
    cat "$LOG_FILE"
    echo "--- End Log File ---"
    rm "$LOG_FILE"
    mv agenttrader/.env.local.bak agenttrader/.env.local
    exit 1
fi
