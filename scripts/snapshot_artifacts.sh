#!/usr/bin/env bash
set -euo pipefail

# Snapshot Artifact Registry inventory for v2 images.
#
# Writes:
#   audit_artifacts/artifacts_snapshot.json
#
# Requires:
# - gcloud authenticated
# - Artifact Registry API access
#
# Env overrides:
# - PROJECT (default: agenttrader-prod)
# - REGION / LOCATION (default: us-east4)
# - AR_REPOS (comma-separated, default: trader-repo)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/audit_artifacts"
OUT_PATH="${OUT_DIR}/artifacts_snapshot.json"

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd gcloud
require_cmd python3

PROJECT="${PROJECT:-agenttrader-prod}"
LOCATION="${LOCATION:-${REGION:-us-east4}}"
AR_REPOS="${AR_REPOS:-trader-repo}"

NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
mkdir -p "${OUT_DIR}"

# Ensure gcloud auth (non-interactive check)
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
  echo "ERROR: No active gcloud account. Run: gcloud auth login" >&2
  exit 1
fi

python3 - "${PROJECT}" "${LOCATION}" "${AR_REPOS}" "${NOW_UTC}" "${OUT_PATH}" <<'PY'
import json
import subprocess
import sys
from typing import Any, Dict, List

project = sys.argv[1]
location = sys.argv[2]
repos_csv = sys.argv[3]
now_utc = sys.argv[4]
out_path = sys.argv[5]

repos = [r.strip() for r in repos_csv.split(",") if r.strip()]
if not repos:
    raise SystemExit("No repos specified (AR_REPOS empty).")

def _run_json(cmd: List[str]) -> Any:
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{p.stderr.strip()}")
    return json.loads(p.stdout or "[]")

all_rows: List[Dict[str, Any]] = []
errors: List[str] = []

for repo in repos:
    base = f"{location}-docker.pkg.dev/{project}/{repo}"
    # Includes tags + digests + create times
    cmd = [
        "gcloud",
        "artifacts",
        "docker",
        "images",
        "list",
        base,
        "--include-tags",
        "--format=json",
    ]
    try:
        rows = _run_json(cmd)
        for r in rows:
            r["_repo"] = repo
            all_rows.append(r)
    except Exception as e:
        errors.append(f"{repo}: {e}")

def _k(row: Dict[str, Any]) -> str:
    return (row.get("package") or "") + "|" + (row.get("version") or row.get("digest") or "")

all_rows.sort(key=_k)

snapshot = {
    "timestamp_utc": now_utc,
    "project": project,
    "location": location,
    "repos": repos,
    "images": all_rows,
    "errors": errors,
}

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(snapshot, f, indent=2, sort_keys=True)
    f.write("\n")

if errors:
    raise SystemExit(f"Artifact snapshot completed with errors in {len(errors)} repo(s). See 'errors' in output.")
PY

echo "OK: wrote ${OUT_PATH}"

