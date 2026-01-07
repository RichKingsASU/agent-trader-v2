#!/usr/bin/env bash
set -euo pipefail

# Backup a GitOps-style snapshot of the v2 Kubernetes state.
#
# Exports YAML (stored as deterministic JSON, which is valid YAML 1.2) for:
# - deploy, sts, svc, cm, sa, role, rolebinding, ingress (if present)
#
# Output:
#   audit_artifacts/cluster_backup/<timestamp>/

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_BASE="${ROOT_DIR}/audit_artifacts/cluster_backup"

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
require_cmd git

NS="${1:-${NAMESPACE:-trading-floor}}"
NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
TS_DIR="$(date -u +'%Y%m%dT%H%M%SZ')"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
KUBE_CONTEXT="$(kubectl config current-context 2>/dev/null || echo "UNKNOWN")"

OUT_DIR="${OUT_BASE}/${TS_DIR}"
mkdir -p "${OUT_DIR}"

python3 - "${NS}" "${OUT_DIR}" <<'PY'
import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

ns = sys.argv[1]
out_dir = sys.argv[2]

kinds = [
    ("deploy", "Deployment"),
    ("sts", "StatefulSet"),
    ("svc", "Service"),
    ("cm", "ConfigMap"),
    ("sa", "ServiceAccount"),
    ("role", "Role"),
    ("rolebinding", "RoleBinding"),
    ("ingress", "Ingress"),
]

def _run(args: List[str]) -> Optional[Dict[str, Any]]:
    p = subprocess.run(["kubectl", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        # treat missing kinds (e.g., ingress in some clusters) as empty
        if "the server doesn't have a resource type" in (p.stderr or ""):
            return {"items": []}
        raise RuntimeError(f"kubectl failed: kubectl {' '.join(args)}\n{p.stderr.strip()}")
    if not p.stdout.strip():
        return {"items": []}
    return json.loads(p.stdout)

def _strip_ephemeral(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj = json.loads(json.dumps(obj))
    obj.pop("status", None)
    md = obj.get("metadata") or {}
    for k in ("managedFields", "resourceVersion", "uid", "generation", "creationTimestamp", "selfLink"):
        md.pop(k, None)
    anns = md.get("annotations") or {}
    anns.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    if not anns:
        md.pop("annotations", None)
    else:
        md["annotations"] = anns
    obj["metadata"] = md
    return obj

for short, display in kinds:
    data = _run(["get", short, "-n", ns, "-o", "json"]) or {"items": []}
    items = data.get("items") or []
    items.sort(key=lambda o: ((o.get("metadata") or {}).get("name") or ""))
    for o in items:
        name = ((o.get("metadata") or {}).get("name") or "unknown")
        cleaned = _strip_ephemeral(o)
        path = os.path.join(out_dir, f"{short}__{name}.yaml")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2, sort_keys=True)
            f.write("\n")
PY

cat > "${OUT_DIR}/README.md" <<EOF
## Cluster state backup

- **Generated (UTC)**: ${NOW_UTC}
- **Namespace**: ${NS}
- **kubectl context**: ${KUBE_CONTEXT}
- **Git SHA**: ${GIT_SHA}

This directory contains one file per resource, exported from the cluster and stripped of ephemeral fields.
EOF

echo "OK: wrote cluster backup to ${OUT_DIR}"

