#!/bin/bash
#
# Convenience script to run the LLM Sentiment Strategy
#
# Usage:
#   ./scripts/run_sentiment_strategy.sh               # Dry run
#   ./scripts/run_sentiment_strategy.sh --execute     # Execute trades
#   ./scripts/run_sentiment_strategy.sh --symbols AAPL,MSFT  # Custom symbols
#

set -e

# Change to repo root
cd "$(dirname "$0")/.."

# Default environment variables (can be overridden)
export STRATEGY_SYMBOLS="${STRATEGY_SYMBOLS:-SPY,QQQ,IWM}"
export VERTEX_AI_MODEL_ID="${VERTEX_AI_MODEL_ID:-gemini-1.5-flash}"

echo "========================================"
echo "LLM Sentiment Strategy Runner"
echo "========================================"
echo "Symbols: $STRATEGY_SYMBOLS"
echo "Model: $VERTEX_AI_MODEL_ID"
echo ""

# Check required env vars
if [ -z "$APCA_API_KEY_ID" ]; then
    echo "ERROR: APCA_API_KEY_ID not set"
    echo "Please set: export APCA_API_KEY_ID=your-key-id"
    exit 1
fi

if [ -z "$APCA_API_SECRET_KEY" ]; then
    echo "ERROR: APCA_API_SECRET_KEY not set"
    echo "Please set: export APCA_API_SECRET_KEY=your-secret-key"
    exit 1
fi

if [ -z "$APCA_API_BASE_URL" ]; then
    echo "ERROR: APCA_API_BASE_URL not set"
    echo "Please set: export APCA_API_BASE_URL=https://paper-api.alpaca.markets"
    exit 1
fi

if [ -z "$FIREBASE_PROJECT_ID" ]; then
    echo "ERROR: FIREBASE_PROJECT_ID not set"
    echo "Please set: export FIREBASE_PROJECT_ID=your-project"
    exit 1
fi

if [ -z "$DATABASE_URL" ]; then
    echo "WARNING: DATABASE_URL not set (PostgreSQL features will be limited)"
fi

# Run the strategy
python3 -m backend.strategy_engine.sentiment_strategy_driver "$@"
