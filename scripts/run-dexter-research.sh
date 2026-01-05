#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 \"Your financial research question\""
  exit 1
fi

QUESTION="$*"

cd "$HOME/dexter"
echo "$QUESTION" | uv run dexter-agent
