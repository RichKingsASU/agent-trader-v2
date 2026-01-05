#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
cd "$FRONTEND_DIR"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: missing required env var: $name" >&2
    return 1
  fi
}

warn_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "WARN: $name is not set" >&2
  fi
}

# Optional: load local env for Vite (recommended)
if [[ -f "$FRONTEND_DIR/.env.local" ]]; then
  echo "Sourcing env from frontend/.env.local"
  set -a
  # shellcheck disable=SC1091
  source "$FRONTEND_DIR/.env.local"
  set +a
fi

need_cmd node
need_cmd npm

# Required Firebase client config for the UI
require_env VITE_FIREBASE_API_KEY || exit 1
require_env VITE_FIREBASE_AUTH_DOMAIN || exit 1
require_env VITE_FIREBASE_PROJECT_ID || exit 1
require_env VITE_FIREBASE_APP_ID || exit 1

# Optional (UI can still load without these in some setups)
warn_env VITE_FIREBASE_STORAGE_BUCKET
warn_env VITE_FIREBASE_MESSAGING_SENDER_ID
warn_env VITE_STREAMER_URL

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Installing frontend dependencies..." >&2
  npm install
fi

FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

echo "Starting frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
