#!/usr/bin/env bash
set -euo pipefail
echo "Checking repo structure..."
BAD=$(grep -R "^(backend|functions|mcp)/" -n . || true)
if [ -n "$BAD" ]; then
  echo "❌ Forbidden legacy roots found:"
  echo "$BAD"
  exit 1
fi
echo "✔ Structure guard passed"
