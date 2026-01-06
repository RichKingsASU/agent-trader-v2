#!/usr/bin/env bash
set -euo pipefail
APPS=(marketdata strategy-gamma strategy-whale strategy-engine congressional-ingest)
for app in "${APPS[@]}"; do
  echo "Verifying image for ${app}"
  if ! gcloud artifacts docker images describe "us-east4-docker.pkg.dev/\${PROJECT_ID}/trader-repo/${app}:latest" > /dev/null 2>&1; then
    echo "❌ Missing image: ${app}"
    exit 1
  fi
done
echo "✔ All images verified"
