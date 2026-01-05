#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== Repo preflight (Alpaca + Firebase) =="

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd git
require_cmd python3
require_cmd npm

echo
echo "== Guardrails: banned strings / secret markers =="
echo "Scanning tracked files for banned vendor references..."
if git grep -n -I -i \
  -e "supa[b]ase" \
  -e "SUPA[B]ASE_" \
  -e "VITE_SUPA[B]ASE" \
  -e "@supa[b]ase" \
  -e "postg[re]st" \
  -e "go[tr]ue" \
  -- . >/dev/null; then
  echo "ERROR: banned vendor reference detected in tracked files." >&2
  exit 1
fi

echo "Scanning tracked files for secret markers..."
if git grep -n -I -E \
  -e "-----BEGIN( [A-Z]+)? PRIVATE KEY-----" \
  -e "\"type\"[[:space:]]*:[[:space:]]*\"service_account\"" \
  -e "\"client_email\"[[:space:]]*:" \
  -e "\"private_key\"[[:space:]]*:" \
  -e "\"private_key_id\"[[:space:]]*:" \
  -- . >/dev/null; then
  echo "ERROR: possible secret material detected in tracked files." >&2
  exit 1
fi

echo
echo "== Backend: compile check =="
python3 -m compileall "${ROOT_DIR}/backend"

echo
echo "== Backend: ingestion dry-run (no creds required) =="
DRY_RUN=1 STOP_AFTER_SECONDS=2 python3 -m backend.ingestion.market_data_ingest

echo
echo "== Frontend: install + build =="
(cd "${ROOT_DIR}/frontend" && npm install && npm run build)

echo
echo "OK: preflight passed"

