#!/usr/bin/env bash
set -euo pipefail

# Capture a deterministic "Last Known Good" (LKG) marker from a running cluster.
#
# - Queries live K8s resources in the target namespace
# - Resolves image digests from pod status (imageID)
# - Writes:
#   - ops/lkg/lkg_manifest.yaml (kubectl-applyable, pinned to digests)
#   - ops/lkg/lkg_metadata.json (inventory + provenance + safety posture)
#
# Safety posture:
# - The generated manifest forces the kill-switch to EXECUTION_HALTED="1"
#   (restore keeps execution disabled).

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/ops/lkg"
MANIFEST_PATH="${OUT_DIR}/lkg_manifest.yaml"
METADATA_PATH="${OUT_DIR}/lkg_metadata.json"

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
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
BUILD_ID="${BUILD_ID:-${CLOUD_BUILD_ID:-${CLOUDBUILD_BUILD_ID:-${GCB_BUILD_ID:-}}}}"

KUBE_CONTEXT="$(kubectl config current-context 2>/dev/null || echo "UNKNOWN")"
CLUSTER_NAME="$(
  kubectl config view --minify -o jsonpath='{.contexts[0].context.cluster}' 2>/dev/null || true
)"
CLUSTER_NAME="${CLUSTER_NAME:-UNKNOWN}"

mkdir -p "${OUT_DIR}"

TMP_MANIFEST="$(mktemp)"
TMP_META="$(mktemp)"
cleanup() {
  rm -f "${TMP_MANIFEST}" "${TMP_META}"
}
trap cleanup EXIT

python3 - "${NS}" "${NOW_UTC}" "${GIT_SHA}" "${BUILD_ID}" "${KUBE_CONTEXT}" "${CLUSTER_NAME}" "${TMP_MANIFEST}" "${TMP_META}" <<'PY'
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

NS = sys.argv[1]
NOW_UTC = sys.argv[2]
GIT_SHA = sys.argv[3]
BUILD_ID = sys.argv[4]
KUBE_CONTEXT = sys.argv[5]
CLUSTER_NAME = sys.argv[6]
OUT_MANIFEST = sys.argv[7]
OUT_META = sys.argv[8]

KILL_SWITCH_NAME = "agenttrader-kill-switch"
KILL_SWITCH_KEY = "EXECUTION_HALTED"
KILL_SWITCH_VALUE = "1"  # force halted in all restores

def _run(*args: str, allow_not_found: bool = False) -> Optional[Dict[str, Any]]:
    cmd = ["kubectl", *args, "-o", "json"]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        if allow_not_found:
            return None
        raise RuntimeError(f"kubectl failed: {' '.join(cmd)}\n{p.stderr.strip()}")
    if not p.stdout.strip():
        return None
    return json.loads(p.stdout)

def _strip_ephemeral(obj: Dict[str, Any]) -> Dict[str, Any]:
    obj = json.loads(json.dumps(obj))  # deep copy
    obj.pop("status", None)
    md = obj.get("metadata") or {}
    for k in (
        "managedFields",
        "resourceVersion",
        "uid",
        "generation",
        "creationTimestamp",
        "selfLink",
    ):
        md.pop(k, None)
    anns = md.get("annotations") or {}
    anns.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    if not anns:
        md.pop("annotations", None)
    else:
        md["annotations"] = anns
    obj["metadata"] = md
    return obj

_DIGEST_RE = re.compile(r"(sha256:[0-9a-f]{32,})")

def _pin_from_image_id(image: str, image_id: str) -> Optional[str]:
    """
    Return a fully-qualified image reference pinned to a sha256 digest.
    Prefers using the full pullable ref when present (docker-pullable://repo@sha256:...).
    """
    if image and "@sha256:" in image:
        return image
    if not image_id:
        return None
    # Typical: docker-pullable://us-east4-docker.pkg.dev/.../img@sha256:...
    if "@" in image_id and "sha256:" in image_id:
        s = image_id
        s = s.replace("docker-pullable://", "").replace("docker://", "").replace("containerd://", "")
        # If there are stray prefixes, keep only the last segment that looks pullable.
        m = re.search(r"([a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{32,})", s)
        return m.group(1) if m else s
    # Some runtimes report only the digest: sha256:...
    m = _DIGEST_RE.search(image_id)
    if m and image:
        return f"{image.split('@')[0]}@{m.group(1)}"
    return None

def _pods_for_selector(selector: Dict[str, Any]) -> List[Dict[str, Any]]:
    match_labels = (selector or {}).get("matchLabels") or {}
    if not match_labels:
        raise RuntimeError("selector.matchLabels missing; cannot deterministically map workload -> pods")
    sel = ",".join(f"{k}={v}" for k, v in sorted(match_labels.items()))
    pods = _run("get", "pods", "-n", NS, "-l", sel) or {"items": []}
    items = pods.get("items") or []
    # deterministic order
    items.sort(key=lambda p: ((p.get("metadata") or {}).get("name") or ""))
    return items

def _pin_workload_images(kind: str, name: str, obj: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    spec = obj.get("spec") or {}
    tpl = ((spec.get("template") or {}).get("spec") or {})
    containers = tpl.get("containers") or []

    pods = _pods_for_selector(spec.get("selector") or {})
    if not pods:
        raise RuntimeError(f"{kind}/{name}: no pods found for selector; cannot resolve digests")

    # Build containerName -> pinned image from observed pods.
    observed: Dict[str, str] = {}
    for pod in pods:
        st = pod.get("status") or {}
        for cs in (st.get("containerStatuses") or []):
            cname = cs.get("name") or ""
            if not cname:
                continue
            pinned = _pin_from_image_id(cs.get("image") or "", cs.get("imageID") or "")
            if not pinned:
                continue
            if cname in observed and observed[cname] != pinned:
                raise RuntimeError(
                    f"{kind}/{name}: container '{cname}' has inconsistent digests across pods:\n"
                    f"  {observed[cname]}\n  {pinned}"
                )
            observed[cname] = pinned

    missing = []
    for c in containers:
        cname = c.get("name") or ""
        cur = c.get("image") or ""
        pinned = observed.get(cname) or (_pin_from_image_id(cur, ""))
        if not pinned or "@sha256:" not in pinned:
            missing.append((cname, cur))
            continue
        c["image"] = pinned

    if missing:
        raise RuntimeError(
            f"{kind}/{name}: missing image digest(s) for containers: "
            + ", ".join(f"{cn}={img}" for cn, img in missing)
        )

    inv = [{"container": (c.get("name") or ""), "image": (c.get("image") or "")} for c in containers]
    inv.sort(key=lambda x: x["container"])
    return obj, inv

items: List[Dict[str, Any]] = []
components: List[Dict[str, Any]] = []
agent_mode_observed: Dict[str, List[str]] = {}

def _maybe_add_single(kind: str, name: str, args: List[str], cluster_scoped: bool = False):
    if cluster_scoped:
        obj = _run("get", kind, name, allow_not_found=True)
    else:
        obj = _run("get", kind, name, "-n", NS, allow_not_found=True)
    if not obj:
        return
    items.append(_strip_ephemeral(obj))

def _add_list(kind: str):
    obj = _run("get", kind, "-n", NS, allow_not_found=True) or {"items": []}
    lst = obj.get("items") or []
    lst.sort(key=lambda o: ((o.get("metadata") or {}).get("name") or ""))
    for o in lst:
        items.append(_strip_ephemeral(o))

# Cluster/namespace bootstrap resources
ns_obj = _run("get", "namespace", NS, allow_not_found=True)
if ns_obj:
    items.append(_strip_ephemeral(ns_obj))
else:
    items.append({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS}})

sa_obj = _run("get", "serviceaccount", "trading-floor-sa", "-n", NS, allow_not_found=True)
if sa_obj:
    items.append(_strip_ephemeral(sa_obj))
else:
    items.append({"apiVersion": "v1", "kind": "ServiceAccount", "metadata": {"name": "trading-floor-sa", "namespace": NS}})

pc_obj = _run("get", "priorityclass", "high-priority", allow_not_found=True)
if pc_obj:
    items.append(_strip_ephemeral(pc_obj))
else:
    items.append({
        "apiVersion": "scheduling.k8s.io/v1",
        "kind": "PriorityClass",
        "metadata": {"name": "high-priority"},
        "value": 1000000,
        "globalDefault": False,
        "description": "This priority class should be used for critical trading strategy pods.",
    })

# Kill switch (force halted)
ks = _run("get", "configmap", KILL_SWITCH_NAME, "-n", NS, allow_not_found=True)
if ks:
    ks = _strip_ephemeral(ks)
    ks.setdefault("data", {})[KILL_SWITCH_KEY] = KILL_SWITCH_VALUE
    items.append(ks)
else:
    # Create it if missing to preserve safety posture
    items.append({
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": KILL_SWITCH_NAME, "namespace": NS},
        "data": {KILL_SWITCH_KEY: KILL_SWITCH_VALUE},
    })

# Namespaced resources
_add_list("service")
_add_list("role")
_add_list("rolebinding")

# Workloads (pin to digests)
for kind, k8s_kind in (("deployment", "Deployment"), ("statefulset", "StatefulSet")):
    obj = _run("get", kind, "-n", NS, allow_not_found=True) or {"items": []}
    lst = obj.get("items") or []
    lst.sort(key=lambda o: ((o.get("metadata") or {}).get("name") or ""))
    for o in lst:
        name = ((o.get("metadata") or {}).get("name") or "")
        pinned_obj, inv = _pin_workload_images(k8s_kind, name, o)

        # Capture any execution-mode style env defaults (for safety posture auditing).
        tpl = (((pinned_obj.get("spec") or {}).get("template") or {}).get("spec") or {})
        for c in (tpl.get("containers") or []):
            for e in (c.get("env") or []):
                k = e.get("name") or ""
                if k.upper() not in ("AGENT_MODE", "EXECUTION_MODE", "TRADING_MODE", "SHADOW_MODE", "PAPER_TRADING"):
                    continue
                if "value" in e:
                    v = e.get("value") or ""
                elif "valueFrom" in e:
                    v = "valueFrom"
                else:
                    v = ""
                agent_mode_observed.setdefault(k, [])
                if v not in agent_mode_observed[k]:
                    agent_mode_observed[k].append(v)

        pinned_obj = _strip_ephemeral(pinned_obj)
        items.append(pinned_obj)
        components.append({
            "kind": k8s_kind,
            "name": name,
            "namespace": NS,
            "containers": inv,
        })

manifest = {"apiVersion": "v1", "kind": "List", "items": items}

meta = {
    "timestamp_utc": NOW_UTC,
    "git_sha": GIT_SHA,
    "build_id": BUILD_ID,
    "cluster_name": CLUSTER_NAME,
    "kubectl_context": KUBE_CONTEXT,
    "namespace": NS,
    "components": components,
    "safety_posture": {
        "execution_halted": True,
        "agent_mode_defaults": {k: sorted(vs) for k, vs in sorted(agent_mode_observed.items())},
        "kill_switch": {
            "configmap": KILL_SWITCH_NAME,
            "key": KILL_SWITCH_KEY,
            "value": KILL_SWITCH_VALUE,
        },
        "notes": "Restore scripts enforce kill-switch halted; execution must remain disabled.",
    },
}

def _dump(path: str, obj: Any):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
        f.write("\n")

_dump(OUT_MANIFEST, manifest)
_dump(OUT_META, meta)
PY

# Atomic write
mv -f "${TMP_MANIFEST}" "${MANIFEST_PATH}"
mv -f "${TMP_META}" "${METADATA_PATH}"

echo "OK: captured LKG"
echo " - manifest:  ${MANIFEST_PATH}"
echo " - metadata:  ${METADATA_PATH}"
echo " - namespace: ${NS}"
echo " - cluster:   ${CLUSTER_NAME}"

