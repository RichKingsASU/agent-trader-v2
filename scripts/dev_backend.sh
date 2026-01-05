#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

require_env_any_of() {
  local found=""
  for name in "$@"; do
    if [[ -n "${!name:-}" ]]; then
      found="$name"
      break
    fi
  done

  if [[ -z "$found" ]]; then
    echo "ERROR: missing required env var (set ONE of):" >&2
    for name in "$@"; do
      echo "  - $name" >&2
    done
    return 1
  fi
}

require_adc() {
  # Allow Firestore emulator mode (no credentials required)
  if [[ -n "${FIRESTORE_EMULATOR_HOST:-}" ]]; then
    return 0
  fi

  # Preferred: explicit credentials file
  if [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
    [[ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]] || die "GOOGLE_APPLICATION_CREDENTIALS is set but file not found: $GOOGLE_APPLICATION_CREDENTIALS"
    return 0
  fi

  # Common local ADC location after `gcloud auth application-default login`
  local gcloud_cfg_dir="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}"
  local adc_file="$gcloud_cfg_dir/application_default_credentials.json"
  [[ -f "$adc_file" ]] || die $'Firebase Admin needs Application Default Credentials.\n\nDo ONE of:\n- Run: gcloud auth application-default login\n- Or set GOOGLE_APPLICATION_CREDENTIALS to a local service account JSON path (do NOT commit it)\n\nOptional: set FIRESTORE_EMULATOR_HOST to use the Firestore emulator without credentials.'
}

# Optional: load local env (names only; never commit secrets)
if [[ -f "$ROOT_DIR/.env.local" ]]; then
  echo "Sourcing env from .env.local (repo root)"
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

need_cmd python3
python3 -m pip --version >/dev/null 2>&1 || die "Missing required Python module: pip (try installing python3-pip)"

# Required for Firestore calls (emulator or real)
require_env_any_of FIREBASE_PROJECT_ID FIRESTORE_PROJECT_ID GOOGLE_CLOUD_PROJECT || exit 1
require_adc

# Ensure Python deps exist; install if missing.
if ! python3 - <<'PY'
import importlib
mods = ("fastapi", "uvicorn", "firebase_admin", "google.cloud.firestore")
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception:
        missing.append(m)
if missing:
    raise SystemExit(2)
PY
then
  echo "Installing Python dependencies..." >&2
  python3 -m pip install -U pip >/dev/null
  python3 -m pip install -r requirements.txt -r backend/risk_service/requirements.txt
fi

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
STRATEGY_SERVICE_PORT="${STRATEGY_SERVICE_PORT:-8001}"
RISK_SERVICE_PORT="${RISK_SERVICE_PORT:-8002}"

echo "Starting backend services:"
echo "- risk_service:     http://${BACKEND_HOST}:${RISK_SERVICE_PORT}"
echo "- strategy_service: http://${BACKEND_HOST}:${STRATEGY_SERVICE_PORT}"

python3 -m uvicorn backend.risk_service.app:app \
  --reload --host "$BACKEND_HOST" --port "$RISK_SERVICE_PORT" &
RISK_PID=$!

python3 -m uvicorn backend.strategy_service.app:app \
  --reload --host "$BACKEND_HOST" --port "$STRATEGY_SERVICE_PORT" &
STRAT_PID=$!

cleanup() {
  set +e
  kill "$RISK_PID" "$STRAT_PID" >/dev/null 2>&1
  wait "$RISK_PID" "$STRAT_PID" >/dev/null 2>&1
}
trap cleanup INT TERM EXIT

wait "$RISK_PID" "$STRAT_PID"
