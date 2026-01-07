#!/usr/bin/env bash
set -euo pipefail

# Validate Cloud Build configurations used by AgentTrader v2.
#
# Checks:
# - All expected configs exist
# - No Docker image references use ":latest" (tags must be immutable / fingerprinted)
# - Build fingerprinting is present (images tagged with $SHORT_SHA / $COMMIT_SHA / explicit _TAG)
#
# Notes:
# - This script only flags ":latest" for container image references.
# - It does not flag secrets like "--update-secrets=...:latest".

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd python3

python3 - "${ROOT_DIR}" <<'PY'
import os
import re
import sys

root = sys.argv[1]

expected = [
    "cloudbuild.yaml",
    "cloudbuild.mcp.yaml",
    "cloudbuild.marketdata.yaml",
    "cloudbuild.strategy.yaml",
    "cloudbuild.strategy-engine.yaml",
    "cloudbuild.strategy-runtime.yaml",
    "cloudbuild.strategy-gamma.yaml",
    "cloudbuild.strategy-whale.yaml",
    "cloudbuild.congressional-ingest.yaml",
    "infra/cloudbuild_congressional_ingest.yaml",
    "infra/cloudbuild_ingest.yaml",
    "infra/cloudbuild_options_ingest.yaml",
    "infra/cloudbuild_strategy_engine.yaml",
    "infra/cloudbuild_stream_bridge.yaml",
]

missing_files = [p for p in expected if not os.path.exists(os.path.join(root, p))]
if missing_files:
    print("ERROR: missing expected Cloud Build configs:", file=sys.stderr)
    for p in missing_files:
        print(f" - {p}", file=sys.stderr)
    raise SystemExit(2)

# Image reference patterns that must not use ":latest"
IMAGE_LATEST_RE = re.compile(
    r"""(?x)
    (
      (?:[a-z0-9.-]+\.)+[a-z]{2,}   # registry-ish
      /[^\s'"]+                    # path
      :latest\b
    )
    |
    (
      \b(?:gcr\.io|us\.gcr\.io|eu\.gcr\.io|asia\.gcr\.io)\b
      /[^\s'"]+
      :latest\b
    )
    """
)

FINGERPRINT_RE = re.compile(r"(\$SHORT_SHA|\$COMMIT_SHA|\$\{SHORT_SHA\}|\$\{COMMIT_SHA\}|\$\{_TAG\}|\$_TAG|\$TAG|\$\{TAG\})")

errors = []
warns = []

for rel in expected:
    path = os.path.join(root, rel)
    with open(path, "r", encoding="utf-8") as f:
        txt = f.read()

    # Ignore secret manager "latest" versions
    scrubbed = re.sub(r"--update-secrets=[^\s]+:latest", "--update-secrets=REDACTED:latest", txt)

    # Disallow image :latest
    m = IMAGE_LATEST_RE.search(scrubbed)
    if m:
        errors.append(f"{rel}: contains ':latest' image reference -> {m.group(0).strip()}")

    # Ensure some immutable fingerprint is present for images
    if "images:" in txt:
        if not FINGERPRINT_RE.search(txt):
            warns.append(f"{rel}: no obvious fingerprint var found (expected $SHORT_SHA / $COMMIT_SHA / _TAG).")

if errors:
    print("ERROR: Cloud Build validation failed:", file=sys.stderr)
    for e in errors:
        print(f" - {e}", file=sys.stderr)
    raise SystemExit(3)

print("OK: Cloud Build configs present and no ':latest' image tags detected.")
if warns:
    print("")
    print("WARN: fingerprint heuristic warnings (review):")
    for w in warns:
        print(f" - {w}")
PY

