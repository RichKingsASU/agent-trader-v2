#!/usr/bin/env bash
set -euo pipefail
echo "Checking for forbidden gcr.io references..."
if grep -R "gcr.io" -n .; then
  echo "❌ gcr.io references found - must use Artifact Registry"
  exit 1
fi
echo "✔ No forbidden gcr.io references"
