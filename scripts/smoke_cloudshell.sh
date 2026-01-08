#!/usr/bin/env bash
set -euo pipefail

echo "== AgentTrader Cloud Shell Smoke Test =="

need_var() {
  local k="$1"
  if [[ -z "${!k:-}" ]]; then
    echo "Missing env var: ${k}" >&2
    exit 2
  fi
}

# Required (do not print values)
need_var "APCA_API_KEY_ID"
need_var "APCA_API_SECRET_KEY"
need_var "APCA_API_BASE_URL"
need_var "DATABASE_URL"

# Run bars ingest once
echo "Running bars ingest once..."
bars_log="$(python3 backend/streams/alpaca_bars_ingest.py 2>&1)"
bars_upserted="$(
  printf "%s\n" "${bars_log}" | python3 - <<'PY'
import re, sys
s=sys.stdin.read()
m=re.search(r"Total bars upserted:\s*(\d+)", s)
print(m.group(1) if m else "unknown")
PY
)"

# Run options snapshots ingest once
echo "Running options snapshots ingest once..."
opts_log="$(python3 backend/streams/alpaca_options_chain_ingest.py 2>&1)"
opts_upserted="$(
  printf "%s\n" "${opts_log}" | python3 - <<'PY'
import re, sys
s=sys.stdin.read()
m=re.search(r"\bupserted=(\d+)\b", s)
print(m.group(1) if m else "unknown")
PY
)"

echo "OK: bars_upserted=${bars_upserted} options_snapshots_upserted=${opts_upserted}"
echo "== Smoke test complete =="
