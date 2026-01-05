#!/usr/bin/env bash
set -euo pipefail

# Smoke test: option contracts + option chain snapshots end-to-end.
#
# Required env vars:
# - DATABASE_URL
# - ALPACA_KEY_ID + ALPACA_SECRET_KEY
#
# Optional env vars:
# - UNDERLYING (default: SPY)
# - ALPACA_TRADING_HOST (default: https://paper-api.alpaca.markets)
# - ALPACA_DATA_HOST (default: https://data.alpaca.markets)

UNDERLYING="${UNDERLYING:-SPY}"
ALPACA_TRADING_HOST="${ALPACA_TRADING_HOST:-https://paper-api.alpaca.markets}"
ALPACA_DATA_HOST="${ALPACA_DATA_HOST:-https://data.alpaca.markets}"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: DATABASE_URL is not set" >&2
  exit 1
fi

if [[ -z "${ALPACA_KEY_ID:-}" || -z "${ALPACA_SECRET_KEY:-}" ]]; then
  echo "ERROR: missing Alpaca credentials. Set ALPACA_KEY_ID and ALPACA_SECRET_KEY." >&2
  exit 1
fi

export UNDERLYING
export ALPACA_TRADING_HOST
export ALPACA_DATA_HOST

# Ensure python deps exist; install if missing.
if ! python3 - <<'PY'
import importlib
missing = []
for m in ("requests", "psycopg"):
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
if missing:
    raise SystemExit(2)
PY
then
  echo "Installing python deps (requests, psycopg[binary])..." >&2
  python3 -m pip install -U "requests" "psycopg[binary]"
fi

echo "Running option-chain ingest for UNDERLYING=${UNDERLYING}" >&2
python3 backend/streams/alpaca_options_chain_ingest.py

echo "Verifying DB has recent rows..." >&2
python3 - <<'PY'
import os
from datetime import datetime, timedelta, timezone
import psycopg

db_url = os.environ["DATABASE_URL"]
underlying = os.environ.get("UNDERLYING", "SPY")

now = datetime.now(timezone.utc)
cutoff = now - timedelta(minutes=15)

with psycopg.connect(db_url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from public.alpaca_option_snapshots where underlying_symbol = %s and snapshot_time >= %s",
            (underlying, cutoff),
        )
        snaps = cur.fetchone()[0]

print(f"OK: option_snapshots(last15m)={snaps}")
if snaps <= 0:
    raise SystemExit(3)
PY
