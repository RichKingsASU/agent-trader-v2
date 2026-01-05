#!/usr/bin/env bash
set -euo pipefail

KEY_PATH="${1:-$HOME/secrets/service-account-key.json}"

export GOOGLE_APPLICATION_CREDENTIALS="$KEY_PATH"
echo "GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"

if [[ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
  echo "OK: credentials file exists"
  exit 0
fi

echo "MISSING: credentials file does not exist at '$GOOGLE_APPLICATION_CREDENTIALS'" >&2
echo "Place your service account JSON there (do not commit it), or use ADC:" >&2
echo "  gcloud auth application-default login" >&2
exit 1

