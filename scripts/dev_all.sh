#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ -x "$ROOT_DIR/scripts/dev_backend.sh" ]] || die "Missing or non-executable: scripts/dev_backend.sh"
[[ -x "$ROOT_DIR/scripts/dev_frontend.sh" ]] || die "Missing or non-executable: scripts/dev_frontend.sh"

echo "Starting backend + frontend (Ctrl+C to stop)..."

"$ROOT_DIR/scripts/dev_backend.sh" &
BACKEND_PID=$!

"$ROOT_DIR/scripts/dev_frontend.sh" &
FRONTEND_PID=$!

cleanup() {
  set +e
  kill "$BACKEND_PID" "$FRONTEND_PID" >/dev/null 2>&1
  wait "$BACKEND_PID" "$FRONTEND_PID" >/dev/null 2>&1
}
trap cleanup INT TERM EXIT

wait "$BACKEND_PID" "$FRONTEND_PID"
