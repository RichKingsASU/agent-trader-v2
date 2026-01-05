#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

MASTER="prompts/master_reasoning_protocol.md"
TASK="${1:-prompts/agenttrader_dev_agent.md}"

if [[ ! -f "$MASTER" ]]; then
  echo "Missing $MASTER" >&2
  exit 1
fi
if [[ ! -f "$TASK" ]]; then
  echo "Missing task prompt: $TASK" >&2
  exit 1
fi

cat "$MASTER" "$TASK" > /tmp/gemini_full_prompt.md

gemini -i "$(cat /tmp/gemini_full_prompt.md)" "${@:2}"
