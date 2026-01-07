#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/deploy_logs"
OUT_FILE="${OUT_DIR}/health_report.md"

# TODO(ops-status): Prefer service `/ops/status` sampling in this report.
# A minimal helper exists at `scripts/report_v2_deploy.py` (fetch_ops_status).
# Integration is deferred until this report has a stable way to discover/resolve
# in-cluster service URLs without long-lived port-forwards.

# Non-interactive / no pagers
export KUBECTL_PAGER=""
export PAGER=cat
export GIT_PAGER=cat
export LESS=-FRSX

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_cmd git
require_cmd kubectl
require_cmd python3

NS="${1:-${NAMESPACE:-}}"
if [[ -z "${NS}" ]]; then
  NS="$(kubectl config view --minify -o jsonpath='{.contexts[0].context.namespace}' 2>/dev/null || true)"
fi
NS="${NS:-default}"

EVENT_LIMIT="${EVENT_LIMIT:-20}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-10s}"

NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
GIT_BRANCH="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "UNKNOWN")"

KUBE_CONTEXT="$(kubectl config current-context 2>/dev/null || echo "UNKNOWN")"
KUBE_CLUSTER="$(kubectl config view --minify -o jsonpath='{.contexts[0].context.cluster}' 2>/dev/null || echo "UNKNOWN")"
KUBE_USER="$(kubectl config view --minify -o jsonpath='{.contexts[0].context.user}' 2>/dev/null || echo "UNKNOWN")"

mkdir -p "${OUT_DIR}"

{
  cat <<EOF
## Deployment Health Report

- **Generated (UTC)**: ${NOW_UTC}
- **Git SHA**: \`${GIT_SHA}\`
- **Git branch**: \`${GIT_BRANCH}\`
- **kubectl context**: \`${KUBE_CONTEXT}\`
- **cluster**: \`${KUBE_CLUSTER}\`
- **user**: \`${KUBE_USER}\`
- **namespace**: \`${NS}\`

EOF

  echo "## Pods status"
  echo
  if ! kubectl get pods -n "${NS}" >/dev/null 2>&1; then
    echo "_ERROR: unable to query pods in namespace \`${NS}\` (check kube context/permissions)._"
    echo
  else
    kubectl get pods -n "${NS}" -o json | python3 - <<'PY'
import datetime as _dt
import json as _json
import sys as _sys

def _parse_ts(s):
    if not s:
        return None
    # Kubernetes timestamps are RFC3339, often with Z.
    s = s.replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(s)
    except Exception:
        return None

def _human_age(created):
    ts = _parse_ts(created)
    if not ts:
        return ""
    now = _dt.datetime.now(_dt.timezone.utc)
    if ts.tzinfo is None:
        # Avoid ad-hoc tzinfo assignment; assume naive is UTC.
        ts = _dt.datetime.fromisoformat(ts.isoformat() + "+00:00")
    delta = now - ts
    secs = max(0, int(delta.total_seconds()))
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    if hrs < 48:
        return f"{hrs}h"
    days = hrs // 24
    return f"{days}d"

def _status_for(pod: dict):
    phase = (pod.get("status") or {}).get("phase") or ""
    statuses = ((pod.get("status") or {}).get("containerStatuses") or [])
    # Prefer more informative reasons if present
    for cs in statuses:
        st = cs.get("state") or {}
        if "waiting" in st and (st["waiting"] or {}).get("reason"):
            return st["waiting"]["reason"]
    for cs in statuses:
        st = cs.get("state") or {}
        if "terminated" in st and (st["terminated"] or {}).get("reason"):
            return st["terminated"]["reason"]
    return phase

data = _json.load(_sys.stdin)
items = data.get("items") or []

print("| Pod | Ready | Status | Restarts | Age | Node | IP |")
print("| --- | --- | --- | --- | --- | --- | --- |")

for pod in sorted(items, key=lambda p: (p.get("metadata") or {}).get("name") or ""):
    meta = pod.get("metadata") or {}
    spec = pod.get("spec") or {}
    st = pod.get("status") or {}
    name = meta.get("name") or ""
    node = spec.get("nodeName") or ""
    ip = st.get("podIP") or ""
    age = _human_age(meta.get("creationTimestamp"))

    statuses = st.get("containerStatuses") or []
    ready_cnt = sum(1 for cs in statuses if cs.get("ready") is True)
    total_cnt = len(statuses) if statuses else len(((spec.get("containers") or [])))
    ready = f"{ready_cnt}/{total_cnt}" if total_cnt else ""

    restarts = sum(int(cs.get("restartCount") or 0) for cs in statuses)
    status = _status_for(pod)

    def esc(x: str):
        return (x or "").replace("|", "\\|")

    print(f"| {esc(name)} | {esc(ready)} | {esc(status)} | {restarts} | {esc(age)} | {esc(node)} | {esc(ip)} |")
PY
    echo
  fi

  echo "## Deployments"
  echo
  if ! kubectl get deployments -n "${NS}" >/dev/null 2>&1; then
    echo "_ERROR: unable to query deployments in namespace \`${NS}\`._"
    echo
  else
    kubectl get deployments -n "${NS}" -o json | python3 - <<'PY'
import datetime as _dt
import json as _json
import sys as _sys

def _parse_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(s)
    except Exception:
        return None

def _human_age(created):
    ts = _parse_ts(created)
    if not ts:
        return ""
    now = _dt.datetime.now(_dt.timezone.utc)
    if ts.tzinfo is None:
        # Avoid ad-hoc tzinfo assignment; assume naive is UTC.
        ts = _dt.datetime.fromisoformat(ts.isoformat() + "+00:00")
    delta = now - ts
    secs = max(0, int(delta.total_seconds()))
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    if hrs < 48:
        return f"{hrs}h"
    days = hrs // 24
    return f"{days}d"

def esc(x: str):
    return (x or "").replace("|", "\\|")

data = _json.load(_sys.stdin)
items = data.get("items") or []

print("| Deployment | Ready | Up-to-date | Available | Age |")
print("| --- | --- | --- | --- | --- |")

for d in sorted(items, key=lambda x: (x.get("metadata") or {}).get("name") or ""):
    meta = d.get("metadata") or {}
    spec = d.get("spec") or {}
    st = d.get("status") or {}
    name = meta.get("name") or ""
    desired = int(spec.get("replicas") or 0)
    ready = int(st.get("readyReplicas") or 0)
    updated = int(st.get("updatedReplicas") or 0)
    avail = int(st.get("availableReplicas") or 0)
    age = _human_age(meta.get("creationTimestamp"))
    print(f"| {esc(name)} | {ready}/{desired} | {updated} | {avail} | {esc(age)} |")
PY
    echo
  fi

  echo "## Deployment rollout status"
  echo
  if ! kubectl get deployments -n "${NS}" >/dev/null 2>&1; then
    echo "_ERROR: unable to query deployments in namespace \`${NS}\`._"
    echo
  else
    echo '```text'
    DEPLOY_NAMES="$(kubectl get deployments -n "${NS}" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
    if [[ -z "${DEPLOY_NAMES}" ]]; then
      echo "No deployments found in namespace ${NS}."
    else
      while IFS= read -r name; do
        [[ -z "${name}" ]] && continue
        kubectl rollout status "deployment/${name}" -n "${NS}" --timeout="${ROLLOUT_TIMEOUT}" 2>&1 || true
      done <<< "${DEPLOY_NAMES}"
    fi
    echo '```'
    echo
  fi

  echo "## Images currently deployed"
  echo
  echo "### Images from deployment specs (tags)"
  echo
  if ! kubectl get deployments -n "${NS}" >/dev/null 2>&1; then
    echo "_ERROR: unable to query deployments in namespace \`${NS}\`._"
    echo
  else
    kubectl get deployments -n "${NS}" -o json | python3 - <<'PY'
import json as _json
import sys as _sys

def esc(x: str):
    return (x or "").replace("|", "\\|")

data = _json.load(_sys.stdin)
items = data.get("items") or []

print("| Deployment | Container | Image |")
print("| --- | --- | --- |")

rows = []
for d in items:
    name = ((d.get("metadata") or {}).get("name") or "")
    tpl = (((d.get("spec") or {}).get("template") or {}).get("spec") or {})
    containers = tpl.get("containers") or []
    for c in containers:
        rows.append((name, c.get("name") or "", c.get("image") or ""))

for name, cname, img in sorted(rows):
    print(f"| {esc(name)} | {esc(cname)} | `{esc(img)}` |")
PY
    echo
  fi

  echo "### Images observed on pods (digests)"
  echo
  if ! kubectl get pods -n "${NS}" >/dev/null 2>&1; then
    echo "_ERROR: unable to query pods in namespace \`${NS}\`._"
    echo
  else
    kubectl get pods -n "${NS}" -o json | python3 - <<'PY'
import json as _json
import re as _re
import sys as _sys

def esc(x: str):
    return (x or "").replace("|", "\\|")

def digest_from_image_id(image_id):
    if not image_id:
        return ""
    # Common forms:
    # - docker-pullable://repo@sha256:...
    # - containerd://sha256:...
    m = _re.search(r"(sha256:[0-9a-f]{16,})", image_id)
    if not m:
        return image_id
    d = m.group(1)
    return d if len(d) <= 20 else (d[:20] + "…")

data = _json.load(_sys.stdin)
items = data.get("items") or []

print("| Pod | Container | Image | Image digest |")
print("| --- | --- | --- | --- |")

rows = []
for pod in items:
    name = ((pod.get("metadata") or {}).get("name") or "")
    statuses = ((pod.get("status") or {}).get("containerStatuses") or [])
    for cs in statuses:
        rows.append((
            name,
            cs.get("name") or "",
            cs.get("image") or "",
            digest_from_image_id(cs.get("imageID") or ""),
        ))

for pod, cname, img, dg in sorted(rows):
    print(f"| {esc(pod)} | {esc(cname)} | `{esc(img)}` | `{esc(dg)}` |")
PY
    echo
  fi

  echo "## Recent warning events (last ${EVENT_LIMIT})"
  echo
  if ! kubectl get events -n "${NS}" >/dev/null 2>&1; then
    echo "_ERROR: unable to query events in namespace \`${NS}\`._"
    echo
  else
    kubectl get events -n "${NS}" -o json | python3 - "${EVENT_LIMIT}" <<'PY'
import datetime as _dt
import json as _json
import sys as _sys

limit = int(_sys.argv[1]) if len(_sys.argv) > 1 else 20

def esc(x: str):
    return (x or "").replace("|", "\\|")

def _parse_ts(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return _dt.datetime.fromisoformat(s)
    except Exception:
        return None

def event_time(ev: dict):
    # Try multiple timestamp fields across k8s versions
    for k in ("eventTime", "lastTimestamp", "firstTimestamp"):
        ts = _parse_ts(ev.get(k))
        if ts:
            return ts
    ts = _parse_ts(((ev.get("metadata") or {}).get("creationTimestamp")))
    return ts or _dt.datetime.fromtimestamp(0, tz=_dt.timezone.utc)

data = _json.load(_sys.stdin)
items = data.get("items") or []
warn = [ev for ev in items if (ev.get("type") or "") == "Warning"]
warn.sort(key=event_time)
warn = warn[-limit:]

print("| Time (UTC) | Reason | Object | Message |")
print("| --- | --- | --- | --- |")

for ev in warn:
    t = event_time(ev).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    reason = ev.get("reason") or ""
    inv = ev.get("involvedObject") or {}
    obj = f"{inv.get('kind') or ''}/{inv.get('name') or ''}".strip("/")
    msg = ev.get("message") or ""
    print(f"| {esc(t)} | {esc(reason)} | {esc(obj)} | {esc(msg)} |")
PY
    echo
  fi

  echo "## Suggested scale-up commands"
  echo
  if ! kubectl get deployments -n "${NS}" >/dev/null 2>&1; then
    echo "_ERROR: unable to query deployments in namespace \`${NS}\`._"
    echo
  else
    kubectl get deployments -n "${NS}" -o json | python3 - "${NS}" <<'PY'
import json as _json
import sys as _sys

ns = _sys.argv[1] if len(_sys.argv) > 1 else "default"
data = _json.load(_sys.stdin)
items = data.get("items") or []

def safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

for d in sorted(items, key=lambda x: (x.get("metadata") or {}).get("name") or ""):
    name = ((d.get("metadata") or {}).get("name") or "")
    desired = safe_int((d.get("spec") or {}).get("replicas"), 0)
    up1 = max(desired + 1, 1)
    dbl = max(desired * 2, 1)
    print(f"- `kubectl -n {ns} scale deployment/{name} --replicas={up1}`  # +1 (safe)")
    print(f"- `kubectl -n {ns} scale deployment/{name} --replicas={dbl}`  # 2x (aggressive)")
    print()
PY
  fi
} > "${OUT_FILE}"

echo "OK: wrote ${OUT_FILE}"

