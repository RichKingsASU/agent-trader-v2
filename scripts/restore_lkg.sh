#!/usr/bin/env bash
set -euo pipefail

# Restore a cluster to the recorded Last Known Good (LKG) state.
#
# - Validates that all workload images in LKG are pinned to digests
# - Applies ops/lkg/lkg_manifest.yaml (server-side apply where possible)
# - Waits for rollouts for Deployments/StatefulSets listed in the manifest
# - Enforces kill-switch EXECUTION_HALTED="1" (execution disabled)
# - Runs scripts/deploy_report.sh afterwards

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LKG_DIR="${ROOT_DIR}/ops/lkg"
MANIFEST_PATH="${MANIFEST_PATH:-${LKG_DIR}/lkg_manifest.yaml}"
METADATA_PATH="${METADATA_PATH:-${LKG_DIR}/lkg_metadata.json}"

export KUBECTL_PAGER=""
export PAGER=cat

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd kubectl
require_cmd python3

NS="${1:-${NAMESPACE:-trading-floor}}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-300s}"

if [[ ! -f "${MANIFEST_PATH}" ]]; then
  echo "ERROR: missing LKG manifest: ${MANIFEST_PATH}" >&2
  exit 1
fi

python3 - "${MANIFEST_PATH}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

items = data.get("items") or []
missing = []
for obj in items:
    kind = obj.get("kind") or ""
    if kind not in ("Deployment", "StatefulSet"):
        continue
    name = ((obj.get("metadata") or {}).get("name") or "")
    tpl = (((obj.get("spec") or {}).get("template") or {}).get("spec") or {})
    containers = tpl.get("containers") or []
    for c in containers:
        img = (c.get("image") or "")
        if "@sha256:" not in img:
            missing.append(f"{kind}/{name}:{c.get('name') or ''} -> {img}")

if missing:
    print("ERROR: LKG manifest contains workload images not pinned to digest:", file=sys.stderr)
    for m in missing:
        print(f" - {m}", file=sys.stderr)
    sys.exit(2)
PY

echo "== Applying LKG manifest (server-side apply) =="
kubectl apply --server-side --force-conflicts --field-manager=agenttrader-dr -f "${MANIFEST_PATH}"

echo "== Waiting for rollouts =="
python3 - "${MANIFEST_PATH}" "${NS}" "${ROLLOUT_TIMEOUT}" <<'PY'
import json
import subprocess
import sys

path = sys.argv[1]
ns = sys.argv[2]
timeout = sys.argv[3]

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

items = data.get("items") or []
workloads = []
for obj in items:
    kind = obj.get("kind") or ""
    if kind not in ("Deployment", "StatefulSet"):
        continue
    name = ((obj.get("metadata") or {}).get("name") or "")
    if name:
        workloads.append((kind.lower(), name))

workloads.sort()
failed = 0
for kind, name in workloads:
    res = f"{kind}/{name}"
    p = subprocess.run(
        ["kubectl", "-n", ns, "rollout", "status", res, f"--timeout={timeout}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    print(p.stdout.rstrip())
    if p.returncode != 0:
        failed += 1

if failed:
    raise SystemExit(failed)
PY

echo "== Enforcing kill switch (execution disabled) =="
kubectl -n "${NS}" patch configmap agenttrader-kill-switch --type merge -p '{"data":{"EXECUTION_HALTED":"1"}}' >/dev/null
kubectl -n "${NS}" get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}' | grep -qx "1"

if [[ -x "${ROOT_DIR}/scripts/deploy_report.sh" ]]; then
  echo "== Deploy report =="
  "${ROOT_DIR}/scripts/deploy_report.sh" "${NS}"
else
  echo "WARN: missing scripts/deploy_report.sh; skipping deploy report." >&2
fi

echo "OK: restored to LKG (namespace=${NS})"

