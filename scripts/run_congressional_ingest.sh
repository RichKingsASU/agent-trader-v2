#!/bin/bash
#
# Run Congressional Disclosure Ingestion Service
#
# Usage:
#   ./scripts/run_congressional_ingest.sh [environment]
#
# Environment: local (default), dev, prod
#

set -euo pipefail

ENVIRONMENT="${1:-local}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Starting Congressional Disclosure Ingestion Service"
echo "Environment: $ENVIRONMENT"
echo ""

# Set environment variables based on environment
case "$ENVIRONMENT" in
  local)
    export TENANT_ID="local"
    export NATS_URL="${NATS_URL:-nats://localhost:4222}"
    export POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-300}"  # 5 min for local testing
    export LOOKBACK_DAYS="${LOOKBACK_DAYS:-7}"
    export QUIVER_API_KEY="${QUIVER_API_KEY:-}"  # Optional for local (uses mock data)
    ;;
  
  dev)
    export TENANT_ID="dev"
    export NATS_URL="${NATS_URL:-nats://nats.dev:4222}"
    export POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-1800}"  # 30 min
    export LOOKBACK_DAYS="${LOOKBACK_DAYS:-7}"
    if [ -z "${QUIVER_API_KEY:-}" ]; then
      echo "⚠️  QUIVER_API_KEY not set. Using mock data."
    fi
    ;;
  
  prod)
    export TENANT_ID="prod"
    export NATS_URL="${NATS_URL:-nats://nats.prod:4222}"
    export POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-3600}"  # 1 hour
    export LOOKBACK_DAYS="${LOOKBACK_DAYS:-7}"
    if [ -z "${QUIVER_API_KEY:-}" ]; then
      echo "❌ ERROR: QUIVER_API_KEY required for production"
      exit 1
    fi
    ;;
  
  *)
    echo "❌ ERROR: Unknown environment: $ENVIRONMENT"
    echo "Valid environments: local, dev, prod"
    exit 1
    ;;
esac

# Display configuration
echo "Configuration:"
echo "  TENANT_ID: $TENANT_ID"
echo "  NATS_URL: $NATS_URL"
echo "  POLL_INTERVAL_SECONDS: $POLL_INTERVAL_SECONDS"
echo "  LOOKBACK_DAYS: $LOOKBACK_DAYS"
echo "  QUIVER_API_KEY: ${QUIVER_API_KEY:+[SET]}"
echo ""

# Check if NATS is reachable (optional)
if command -v nc &> /dev/null; then
  NATS_HOST=$(echo "$NATS_URL" | sed 's|nats://||' | cut -d: -f1)
  NATS_PORT=$(echo "$NATS_URL" | sed 's|nats://||' | cut -d: -f2)
  NATS_PORT="${NATS_PORT:-4222}"
  
  if nc -z "$NATS_HOST" "$NATS_PORT" 2>/dev/null; then
    echo "✅ NATS is reachable at $NATS_HOST:$NATS_PORT"
  else
    echo "⚠️  WARNING: Cannot reach NATS at $NATS_HOST:$NATS_PORT"
    echo "   Make sure NATS is running before starting the service."
  fi
  echo ""
fi

# Change to project root
cd "$PROJECT_ROOT"

# Run the ingestion service
echo "🏃 Running ingestion service..."
echo ""

export PYTHONPATH="$PROJECT_ROOT:${PYTHONPATH:-}"

exec python3 -m backend.ingestion.congressional_disclosures
