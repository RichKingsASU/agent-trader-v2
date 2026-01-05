#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

echo "[agents] Activating venv..."
source .venv/bin/activate

echo "[agents] Running GitHub sync (daily-git-sync.sh)..."
./daily-git-sync.sh "$REPO_DIR"

echo "[agents] Running bootstrap_agenttrader.sh (backends + dummy market streamer)..."
./scripts/bootstrap_agenttrader.sh

echo "[agents] All agents completed."
