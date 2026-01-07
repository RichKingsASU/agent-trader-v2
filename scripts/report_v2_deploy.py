#!/usr/bin/env python3
"""
AgentTrader v2 - Deployment Report Generator (GKE/Kubernetes)

Design goals:
- Deterministic, calm reporting: "what is deployed, where, with what image, is it healthy, is it allowed to run?"
- No Kubernetes client dependencies; uses `kubectl ... -o json`.
- Works locally OR in-cluster (service account) as long as `kubectl` can reach the API.
- Degrades gracefully without cluster access (still emits markdown + json reports).

ABSOLUTE RULES:
- Do NOT enable trading. This script is read-only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import shlex
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


LABEL_PART_OF_KEY = "app.kubernetes.io/part-of"
LABEL_PART_OF_VAL = "agent-trader-v2"

REQUIRED_LABELS = [
    ("app.kubernetes.io/name", "agenttrader"),
    (LABEL_PART_OF_KEY, LABEL_PART_OF_VAL),
    # ("app.kubernetes.io/component", "<marketdata|strategy|ops|ingest|mcp>"),
    # ("app.kubernetes.io/instance", "<workload name>"),
]

ENV_KEYS_OF_INTEREST = ["REPO_ID", "AGENT_NAME", "AGENT_ROLE", "AGENT_MODE", "KILL_SWITCH"]


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except Exception:
        return None


def _truthy(v: str) -> bool:
    return (v or "").strip().lower() in {"1", "true", "t", "yes", "y", "on", "enabled"}


def _cmd_str(cmd: List[str]) -> str:
    return " ".join(shlex.quote(c) for c in cmd)


def _run(
    cmd: List[str],
    timeout_s: float = 8.0,
    check: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=check,
            env=env,
            text=True,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError as e:
        return 127, "", str(e)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else ""
        return 124, out, err or f"timeout after {timeout_s}s"
    except Exception as e:
        return 1, "", str(e)


def _read_text_best_effort(path: Path, max_bytes: int = 512_000) -> str:
    try:
        data = path.read_bytes()
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _infer_namespace_from_repo_k8s_dir(repo_root: Path) -> Optional[str]:
    """
    "default namespace 'default' unless k8s/ indicates otherwise"
    We avoid YAML deps: perform best-effort parsing for `kind: Namespace` + `metadata: name:`.
    """
    k8s_dir = repo_root / "k8s"
    if not k8s_dir.exists() or not k8s_dir.is_dir():
        return None

    ns_names: List[str] = []
    for p in sorted(k8s_dir.glob("*.yaml")):
        txt = _read_text_best_effort(p)
        if not txt.strip():
            continue

        # Split documents; parse minimal patterns.
        for doc in re.split(r"^---\s*$", txt, flags=re.MULTILINE):
            if re.search(r"(?m)^\s*kind\s*:\s*Namespace\s*$", doc) is None:
                continue
            m = re.search(
                r"(?ms)^\s*metadata\s*:\s*\n(?:\s+[^\n]+\n)*?\s*name\s*:\s*([^\s#]+)\s*$",
                doc,
            )
            if m:
                ns_names.append(m.group(1).strip())

    ns_names = [n for n in ns_names if n]
    if len(set(ns_names)) == 1:
        return ns_names[0]
    return None


def _kubectl_base_cmd(context: Optional[str]) -> List[str]:
    cmd = ["kubectl"]
    if context:
        cmd += ["--context", context]
    return cmd


def _kubectl_get_json(
    context: Optional[str],
    namespace: str,
    resource: str,
    label_selector: Optional[str],
    timeout_s: float = 10.0,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    cmd = _kubectl_base_cmd(context) + ["-n", namespace, "get", resource, "-o", "json"]
    if label_selector:
        cmd += ["-l", label_selector]
    rc, out, err = _run(cmd, timeout_s=timeout_s)
    if rc != 0:
        return None, f"{_cmd_str(cmd)} failed (rc={rc}): {err.strip() or out.strip()}"
    try:
        return json.loads(out), None
    except Exception as e:
        return None, f"{_cmd_str(cmd)} returned non-JSON output: {e}"


def _kubectl_context_info(context: Optional[str]) -> Dict[str, str]:
    info: Dict[str, str] = {}
    rc, out, _ = _run(_kubectl_base_cmd(context) + ["config", "current-context"], timeout_s=3.0)
    info["current_context"] = out.strip() if rc == 0 else "UNKNOWN"

    rc, out, err = _run(_kubectl_base_cmd(context) + ["config", "view", "--minify", "-o", "json"], timeout_s=5.0)
    if rc != 0:
        info["cluster"] = "UNKNOWN"
        info["user"] = "UNKNOWN"
        info["namespace_from_context"] = ""
        info["error"] = err.strip() or out.strip()
        return info

    try:
        cfg = json.loads(out)
        ctx = ((cfg.get("contexts") or [{}])[0].get("context") or {})
        info["cluster"] = str(ctx.get("cluster") or "UNKNOWN")
        info["user"] = str(ctx.get("user") or "UNKNOWN")
        info["namespace_from_context"] = str(ctx.get("namespace") or "")
    except Exception as e:
        info["cluster"] = "UNKNOWN"
        info["user"] = "UNKNOWN"
        info["namespace_from_context"] = ""
        info["error"] = f"failed to parse kubeconfig json: {e}"
    return info


def _choose_namespace(args_ns: Optional[str]) -> str:
    if args_ns:
        return args_ns
    if os.getenv("KUBERNETES_NAMESPACE"):
        return os.getenv("KUBERNETES_NAMESPACE", "default")
    if os.getenv("NAMESPACE"):
        return os.getenv("NAMESPACE", "default")

    # Try kubeconfig minify namespace; else fall back to inferred repo `k8s/` namespace; else default.
    cfg_ns = ""
    rc, out, _ = _run(["kubectl", "config", "view", "--minify", "-o", "json"], timeout_s=4.0)
    if rc == 0:
        try:
            cfg = json.loads(out)
            cfg_ns = str((((cfg.get("contexts") or [{}])[0].get("context") or {}).get("namespace") or ""))
        except Exception:
            cfg_ns = ""
    if cfg_ns:
        return cfg_ns

    repo_root = Path(__file__).resolve().parents[1]
    inferred = _infer_namespace_from_repo_k8s_dir(repo_root)
    return inferred or "default"


def _json_get(d: Dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = d
    for seg in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(seg)
        if cur is None:
            return default
    return cur


def _summarize_pods_for_workload(workload_uid: str, pods: List[Dict[str, Any]], pod_owner_uid_map: Dict[str, str]) -> Dict[str, int]:
    """
    pod_owner_uid_map: pod_uid -> top-level workload uid
    """
    c = {
        "running": 0,
        "pending": 0,
        "succeeded": 0,
        "failed": 0,
        "unknown": 0,
        "crashloop": 0,
        "imagepull": 0,
    }
    for p in pods:
        pod_uid = str(_json_get(p, "metadata.uid", ""))
        if not pod_uid or pod_owner_uid_map.get(pod_uid) != workload_uid:
            continue
        phase = str(_json_get(p, "status.phase", "Unknown"))
        c_phase = phase.strip().lower()

        # Detect CrashLoopBackOff / ImagePullBackOff etc.
        statuses = _json_get(p, "status.containerStatuses", []) or []
        reasons = []
        for cs in statuses:
            st = cs.get("state") or {}
            if isinstance(st, dict) and "waiting" in st and isinstance(st["waiting"], dict):
                r = st["waiting"].get("reason")
                if r:
                    reasons.append(str(r))
        if any(r in {"CrashLoopBackOff", "Error"} for r in reasons):
            c["crashloop"] += 1
        if any(r in {"ImagePullBackOff", "ErrImagePull"} for r in reasons):
            c["imagepull"] += 1

        if c_phase == "running":
            c["running"] += 1
        elif c_phase == "pending":
            c["pending"] += 1
        elif c_phase == "succeeded":
            c["succeeded"] += 1
        elif c_phase == "failed":
            c["failed"] += 1
        else:
            c["unknown"] += 1
    return c


def _digest_from_image_id(image_id: str) -> Optional[str]:
    if not image_id:
        return None
    # Common forms:
    # - docker-pullable://repo@sha256:...
    # - containerd://sha256:...
    m = re.search(r"(sha256:[0-9a-f]{16,})", image_id)
    if not m:
        return None
    return m.group(1)


def _observed_image_digests_for_workload(
    workload_uid: str, pods: List[Dict[str, Any]], pod_owner_uid_map: Dict[str, str]
) -> Dict[str, List[str]]:
    """
    Return container_name -> list of digests observed on pods (best-effort).
    """
    digests: Dict[str, set] = {}
    for p in pods:
        pod_uid = str(_json_get(p, "metadata.uid", ""))
        if not pod_uid or pod_owner_uid_map.get(pod_uid) != workload_uid:
            continue
        for cs in (_json_get(p, "status.containerStatuses", []) or []):
            if not isinstance(cs, dict):
                continue
            cname = str(cs.get("name") or "")
            dg = _digest_from_image_id(str(cs.get("imageID") or ""))
            if not cname or not dg:
                continue
            digests.setdefault(cname, set()).add(dg)
    return {k: sorted(v) for k, v in digests.items()}


def _resources_for_containers(tpl_spec: Dict[str, Any]) -> Dict[str, Any]:
    def pick(ctr: Dict[str, Any]) -> Dict[str, Any]:
        res = ctr.get("resources") or {}
        req = res.get("requests") or {}
        lim = res.get("limits") or {}
        return {
            "requests": {"cpu": req.get("cpu"), "memory": req.get("memory")},
            "limits": {"cpu": lim.get("cpu"), "memory": lim.get("memory")},
        }

    containers = tpl_spec.get("containers") or []
    init_containers = tpl_spec.get("initContainers") or []
    return {
        "containers": {c.get("name") or "": pick(c) for c in containers if isinstance(c, dict)},
        "initContainers": {c.get("name") or "": pick(c) for c in init_containers if isinstance(c, dict)},
    }


def _images_for_containers(tpl_spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for kind_key in ("initContainers", "containers"):
        for c in (tpl_spec.get(kind_key) or []):
            if not isinstance(c, dict):
                continue
            out.append(
                {
                    "container_type": "init" if kind_key == "initContainers" else "app",
                    "container_name": c.get("name"),
                    "image": c.get("image"),
                    "image_pull_policy": c.get("imagePullPolicy") or "default",
                }
            )
    return out


def _env_summary_for_containers(tpl_spec: Dict[str, Any]) -> Dict[str, Any]:
    """
    Summarize required env keys across all containers.
    - If multiple containers set different values, mark as "mixed".
    - If value comes from valueFrom, report as "set (valueFrom)".
    - For potential secrets (KEY/SECRET/TOKEN/PASSWORD), never print value; just presence.
    """

    def is_sensitive_name(name: str) -> bool:
        n = (name or "").upper()
        return any(x in n for x in ["KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE"])

    values_by_key: Dict[str, List[str]] = {k: [] for k in ENV_KEYS_OF_INTEREST}

    for c in (tpl_spec.get("initContainers") or []) + (tpl_spec.get("containers") or []):
        if not isinstance(c, dict):
            continue
        for e in (c.get("env") or []):
            if not isinstance(e, dict):
                continue
            name = str(e.get("name") or "")
            if name not in values_by_key:
                continue
            if "valueFrom" in e and e["valueFrom"] is not None:
                values_by_key[name].append("set (valueFrom)")
            else:
                v = str(e.get("value") or "")
                if is_sensitive_name(name):
                    values_by_key[name].append("set (redacted)")
                else:
                    values_by_key[name].append(v if v else "set")

    summary: Dict[str, Any] = {}
    for k, vals in values_by_key.items():
        vals = [v for v in vals if v is not None and v != ""]
        if not vals:
            summary[k] = {"present": False, "value": None}
            continue
        uniq = sorted(set(vals))
        if len(uniq) == 1:
            summary[k] = {"present": True, "value": uniq[0]}
        else:
            summary[k] = {"present": True, "value": "mixed"}
    return summary


def _allowed_to_run(env_summary: Dict[str, Any]) -> Tuple[bool, str]:
    kill = env_summary.get("KILL_SWITCH") or {}
    mode = env_summary.get("AGENT_MODE") or {}

    kill_val = str(kill.get("value") or "")
    mode_val = str(mode.get("value") or "")

    if kill.get("present") and _truthy(kill_val):
        return False, "halted (KILL_SWITCH)"
    if mode.get("present") and mode_val.strip().lower() in {"off", "halted", "paused", "disabled"}:
        return False, f"halted (AGENT_MODE={mode_val})"
    return True, "allowed"


def _choose_local_port() -> int:
    # Find a free local port; best-effort.
    for _ in range(20):
        cand = random.randint(18080, 18999)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", cand))
                return cand
            except OSError:
                continue
    # Fallback: OS assigned port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class HealthResult:
    path: str
    ok: bool
    status_code: Optional[int]
    excerpt: str
    error: Optional[str] = None


def _redact_json(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            kk = str(k)
            if any(x in kk.lower() for x in ["secret", "token", "password", "private", "key"]):
                out[kk] = "REDACTED"
            else:
                out[kk] = _redact_json(v)
        return out
    if isinstance(obj, list):
        return [_redact_json(x) for x in obj[:25]]
    if isinstance(obj, str):
        # Redact obvious high-entropy-ish strings (very light heuristic).
        if len(obj) > 64 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", obj):
            return obj[:6] + "…" + obj[-6:]
        return obj
    return obj


def _http_get_json_excerpt(url: str, timeout_s: float = 2.0) -> Tuple[Optional[int], str, Optional[str]]:
    req = urllib.request.Request(url, headers={"User-Agent": "agent-trader-v2-deploy-report/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            code = int(getattr(resp, "status", 200))
            raw = resp.read(24_000)
            txt = raw.decode("utf-8", errors="replace").strip()
            # Try JSON; otherwise show small text excerpt.
            excerpt = ""
            try:
                obj = json.loads(txt) if txt else {}
                red = _redact_json(obj)
                excerpt = json.dumps(red, sort_keys=True)[:400]
            except Exception:
                excerpt = (txt[:300] + ("…" if len(txt) > 300 else "")) if txt else ""
            return code, excerpt, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        excerpt = body[:200] + ("…" if len(body) > 200 else "")
        return int(e.code), excerpt, f"HTTPError {e.code}"
    except Exception as e:
        return None, "", str(e)


def _port_forward_and_probe(
    context: Optional[str],
    namespace: str,
    service_name: str,
    service_port: int,
    probe_paths: List[str],
    timeout_s_per_path: float = 2.0,
) -> List[HealthResult]:
    local_port = _choose_local_port()
    cmd = _kubectl_base_cmd(context) + [
        "-n",
        namespace,
        "port-forward",
        f"svc/{service_name}",
        f"{local_port}:{service_port}",
    ]

    # Start port-forward; kubectl writes "Forwarding from ..." to stderr.
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as e:
        return [HealthResult(path=p, ok=False, status_code=None, excerpt="", error=str(e)) for p in probe_paths]

    try:
        # Wait briefly for readiness.
        ready = False
        start = time.time()
        while time.time() - start < 2.0:
            if proc.poll() is not None:
                break
            line = ""
            try:
                if proc.stderr:
                    line = proc.stderr.readline().strip()
            except Exception:
                line = ""
            if "Forwarding from" in line:
                ready = True
                break
            time.sleep(0.05)

        if not ready and proc.poll() is not None:
            err = ""
            try:
                err = (proc.stderr.read() if proc.stderr else "") or ""
            except Exception:
                err = ""
            return [HealthResult(path=p, ok=False, status_code=None, excerpt="", error=err.strip() or "port-forward failed") for p in probe_paths]

        results: List[HealthResult] = []
        base = f"http://127.0.0.1:{local_port}"
        for pth in probe_paths:
            url = base + pth
            code, excerpt, err = _http_get_json_excerpt(url, timeout_s=timeout_s_per_path)
            ok = bool(code) and 200 <= int(code) < 300
            results.append(HealthResult(path=pth, ok=ok, status_code=code, excerpt=excerpt, error=err))
        return results
    finally:
        # Terminate port-forward reliably.
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


def _owner_uid(obj: Dict[str, Any]) -> str:
    return str(_json_get(obj, "metadata.uid", ""))


def _build_pod_owner_map(
    pods: List[Dict[str, Any]],
    replica_sets: List[Dict[str, Any]],
    deployments: List[Dict[str, Any]],
    statefulsets: List[Dict[str, Any]],
    jobs: List[Dict[str, Any]],
) -> Dict[str, str]:
    """
    Return: pod_uid -> top-level owner workload uid (Deployment/StatefulSet/Job), when known.
    """
    rs_uid_to_deploy_uid: Dict[str, str] = {}
    deploy_uid_by_name: Dict[str, str] = {d.get("metadata", {}).get("name", ""): _owner_uid(d) for d in deployments}
    sset_uid_by_name: Dict[str, str] = {s.get("metadata", {}).get("name", ""): _owner_uid(s) for s in statefulsets}
    job_uid_by_name: Dict[str, str] = {j.get("metadata", {}).get("name", ""): _owner_uid(j) for j in jobs}

    for rs in replica_sets:
        rs_uid = _owner_uid(rs)
        for ref in (_json_get(rs, "metadata.ownerReferences", []) or []):
            if not isinstance(ref, dict):
                continue
            if ref.get("kind") == "Deployment" and ref.get("name") in deploy_uid_by_name:
                rs_uid_to_deploy_uid[rs_uid] = deploy_uid_by_name[ref.get("name")]

    pod_uid_to_workload_uid: Dict[str, str] = {}
    rs_uid_by_name: Dict[str, str] = {r.get("metadata", {}).get("name", ""): _owner_uid(r) for r in replica_sets}

    for p in pods:
        pod_uid = _owner_uid(p)
        refs = _json_get(p, "metadata.ownerReferences", []) or []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            kind = ref.get("kind")
            name = ref.get("name")
            if kind == "StatefulSet" and name in sset_uid_by_name:
                pod_uid_to_workload_uid[pod_uid] = sset_uid_by_name[name]
                break
            if kind == "Job" and name in job_uid_by_name:
                pod_uid_to_workload_uid[pod_uid] = job_uid_by_name[name]
                break
            if kind == "ReplicaSet" and name in rs_uid_by_name:
                rs_uid = rs_uid_by_name[name]
                if rs_uid in rs_uid_to_deploy_uid:
                    pod_uid_to_workload_uid[pod_uid] = rs_uid_to_deploy_uid[rs_uid]
                    break
    return pod_uid_to_workload_uid


def _service_dns_url(svc: Dict[str, Any]) -> str:
    name = str(_json_get(svc, "metadata.name", ""))
    ns = str(_json_get(svc, "metadata.namespace", "default"))
    ports = _json_get(svc, "spec.ports", []) or []
    port = None
    if ports and isinstance(ports, list) and isinstance(ports[0], dict):
        port = ports[0].get("port")
    port = int(port) if port is not None else 80
    return f"http://{name}.{ns}.svc.cluster.local:{port}"


def _service_port(svc: Dict[str, Any]) -> Optional[int]:
    ports = _json_get(svc, "spec.ports", []) or []
    if not ports or not isinstance(ports, list) or not isinstance(ports[0], dict):
        return None
    p = ports[0].get("port")
    try:
        return int(p)
    except Exception:
        return None


def _mk_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("meta") or {}
    summary = report.get("summary") or {}
    workloads = report.get("workloads") or []
    issues = report.get("top_issues") or []
    actions = report.get("recommended_actions") or []

    def fmt_bool(b: Any) -> str:
        return "yes" if b else "no"

    lines: List[str] = []
    lines.append("## AgentTrader v2 — Deployment Report")
    lines.append("")
    lines.append(f"- **Generated (UTC)**: {meta.get('generated_utc')}")
    lines.append(f"- **kubectl context**: `{meta.get('kube_context')}`")
    lines.append(f"- **cluster**: `{meta.get('kube_cluster')}`")
    lines.append(f"- **user**: `{meta.get('kube_user')}`")
    lines.append(f"- **namespace**: `{meta.get('namespace')}`")
    if meta.get("cluster_access") is False:
        lines.append(f"- **cluster access**: **no** (report degraded: {meta.get('cluster_error')})")
    else:
        lines.append(f"- **cluster access**: **yes**")
    lines.append("")

    # Executive summary
    lines.append("## Executive summary")
    lines.append("")
    lines.append(
        f"- **Workloads found**: {summary.get('workloads_total', 0)} "
        f"(Deployments={summary.get('deployments', 0)}, StatefulSets={summary.get('statefulsets', 0)}, Jobs={summary.get('jobs', 0)})"
    )
    if summary.get("jobs", 0):
        lines.append(f"- **Jobs active**: {summary.get('jobs_active', 0)}")
    lines.append(f"- **Healthy (sampled)**: {summary.get('healthy', 0)}")
    lines.append(f"- **Degraded**: {summary.get('degraded', 0)}")
    lines.append(f"- **Halted / not allowed**: {summary.get('halted', 0)}")
    lines.append("")

    # LIVE vs OFF table
    lines.append("## LIVE vs OFF")
    lines.append("")
    lines.append("| Workload | Kind | Allowed to run | Reason | Replicas ready |")
    lines.append("| --- | --- | --- | --- | --- |")
    for w in workloads:
        allowed = bool(w.get("allowed_to_run"))
        allowed_s = "LIVE" if allowed else "OFF"
        rr = ""
        if w.get("replicas_desired") is not None:
            rr = f"{w.get('replicas_ready', 0)}/{w.get('replicas_desired', 0)}"
        lines.append(
            f"| `{w.get('workload_name')}` | {w.get('kind')} | **{allowed_s}** | {w.get('allowed_reason','')} | {rr} |"
        )
    lines.append("")

    # Top issues
    lines.append("## Top Issues")
    lines.append("")
    if not issues:
        lines.append("- _None detected (based on current sampling)._")
    else:
        for it in issues[:12]:
            lines.append(f"- **{it.get('workload','(cluster)')}**: {it.get('issue')}")
    lines.append("")

    # Recommended actions
    lines.append("## Recommended Actions")
    lines.append("")
    if not actions:
        lines.append("- _No actions recommended._")
    else:
        for a in actions[:12]:
            lines.append(f"- {a}")
    lines.append("")

    # Per-workload detail
    lines.append("## Workloads")
    lines.append("")
    for w in workloads:
        lines.append(f"### `{w.get('workload_name')}` ({w.get('kind')})")
        lines.append("")
        lines.append(f"- **Namespace**: `{w.get('namespace')}`")
        lines.append(f"- **Component**: `{w.get('labels', {}).get('app.kubernetes.io/component', '')}`")
        lines.append(f"- **Allowed to run**: **{fmt_bool(w.get('allowed_to_run'))}** ({w.get('allowed_reason')})")
        if w.get("replicas_desired") is not None:
            lines.append(f"- **Replicas**: ready {w.get('replicas_ready', 0)} / desired {w.get('replicas_desired', 0)}")
        if w.get("kind") == "Job" and w.get("job_status"):
            js = w.get("job_status") or {}
            lines.append(
                f"- **Job status**: active={js.get('active',0)} succeeded={js.get('succeeded',0)} failed={js.get('failed',0)} "
                f"(start={js.get('start_time')}, completion={js.get('completion_time')})"
            )
        lines.append(f"- **Pod status summary**: {w.get('pod_status_summary')}")
        lines.append(f"- **Service account**: `{w.get('service_account')}`")
        lines.append("")

        # Images
        lines.append("**Images**")
        lines.append("")
        lines.append("| Container | Type | Image | Pull policy |")
        lines.append("| --- | --- | --- | --- |")
        for im in (w.get("images") or []):
            lines.append(
                f"| `{im.get('container_name','')}` | {im.get('container_type')} | `{im.get('image','')}` | `{im.get('image_pull_policy','')}` |"
            )
        lines.append("")
        dig = w.get("observed_image_digests") or {}
        if dig:
            # Keep this compact; only show first digest per container.
            parts = []
            for cname in sorted(dig.keys()):
                dgs = dig.get(cname) or []
                if dgs:
                    parts.append(f"{cname}={dgs[0]}")
            if parts:
                lines.append(f"- **Observed digests (pods)**: `{', '.join(parts)}`")
                lines.append("")

        # Resources
        lines.append("**Resources (cpu/mem)**")
        lines.append("")
        lines.append("| Container | Requests | Limits |")
        lines.append("| --- | --- | --- |")
        res = w.get("resources") or {}
        for cname, rv in sorted((res.get("containers") or {}).items()):
            req = rv.get("requests") or {}
            lim = rv.get("limits") or {}
            lines.append(
                f"| `{cname}` | {req.get('cpu','')}/{req.get('memory','')} | {lim.get('cpu','')}/{lim.get('memory','')} |"
            )
        lines.append("")

        # Env summary
        lines.append("**Env summary (selected)**")
        lines.append("")
        envs = w.get("env_summary") or {}
        lines.append("| Key | Present | Value |")
        lines.append("| --- | --- | --- |")
        for k in ENV_KEYS_OF_INTEREST:
            kv = envs.get(k) or {}
            lines.append(f"| `{k}` | {fmt_bool(kv.get('present'))} | `{kv.get('value')}` |")
        lines.append("")

        # Health
        lines.append("**Health**")
        lines.append("")
        lines.append(f"- **Service DNS URL (if any)**: `{w.get('health', {}).get('cluster_dns_url', 'unknown')}`")
        samples = (w.get("health", {}).get("samples") or [])
        if not samples:
            lines.append("- **Sampling**: _not available_")
        else:
            for s in samples:
                ok = "ok" if s.get("ok") else "fail"
                lines.append(
                    f"- `{s.get('path')}`: **{ok}** (status={s.get('status_code')}) excerpt=`{s.get('excerpt','')}`"
                )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="AgentTrader v2 deployment report generator (kubectl-based).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--namespace", default=None, help="Kubernetes namespace to inspect.")
    ap.add_argument("--context", default=None, help="kubectl context override.")
    ap.add_argument(
        "--label-selector",
        default=f"{LABEL_PART_OF_KEY}={LABEL_PART_OF_VAL}",
        help="Label selector to scope AgentTrader v2 workloads.",
    )
    ap.add_argument("--output-dir", default="audit_artifacts", help="Output directory for artifacts.")
    ap.add_argument("--skip-health", action="store_true", help="Skip port-forward health sampling.")
    args = ap.parse_args()

    namespace = _choose_namespace(args.namespace)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    ctx_info = _kubectl_context_info(args.context)
    meta: Dict[str, Any] = {
        "generated_utc": _utc_now_iso(),
        "namespace": namespace,
        "kube_context": ctx_info.get("current_context", "UNKNOWN"),
        "kube_cluster": ctx_info.get("cluster", "UNKNOWN"),
        "kube_user": ctx_info.get("user", "UNKNOWN"),
        "label_selector": args.label_selector,
        "cluster_access": True,
        "cluster_error": None,
    }

    # Query resources
    errors: List[str] = []
    deployments_json, e = _kubectl_get_json(args.context, namespace, "deployments", args.label_selector)
    if e:
        errors.append(e)
    statefulsets_json, e = _kubectl_get_json(args.context, namespace, "statefulsets", args.label_selector)
    if e:
        errors.append(e)
    jobs_json, e = _kubectl_get_json(args.context, namespace, "jobs", args.label_selector)
    if e:
        errors.append(e)
    services_json, e = _kubectl_get_json(args.context, namespace, "services", args.label_selector)
    if e:
        errors.append(e)
    pods_json, e = _kubectl_get_json(args.context, namespace, "pods", args.label_selector)
    if e:
        errors.append(e)
    rs_json, e = _kubectl_get_json(args.context, namespace, "replicasets", args.label_selector)
    if e:
        # Not fatal; mapping pods to deployments becomes weaker.
        errors.append(e)

    if deployments_json is None and statefulsets_json is None and jobs_json is None and services_json is None:
        meta["cluster_access"] = False
        meta["cluster_error"] = errors[0] if errors else "unable to query cluster (unknown error)"

    deployments = (deployments_json or {}).get("items") or []
    statefulsets = (statefulsets_json or {}).get("items") or []
    jobs = (jobs_json or {}).get("items") or []
    services = (services_json or {}).get("items") or []
    pods = (pods_json or {}).get("items") or []
    replica_sets = (rs_json or {}).get("items") or []

    # Build mapping pods -> top-level workload uid
    pod_owner = _build_pod_owner_map(pods, replica_sets, deployments, statefulsets, jobs) if pods else {}

    # Map services to "instance"
    svc_by_instance: Dict[str, Dict[str, Any]] = {}
    for s in services:
        labels = (_json_get(s, "metadata.labels", {}) or {}) if isinstance(_json_get(s, "metadata.labels", {}), dict) else {}
        inst = str(labels.get("app.kubernetes.io/instance") or _json_get(s, "metadata.name", ""))
        if inst:
            svc_by_instance[inst] = s

    workloads_out: List[Dict[str, Any]] = []

    def add_workload(kind: str, obj: Dict[str, Any]) -> None:
        name = str(_json_get(obj, "metadata.name", ""))
        uid = _owner_uid(obj)
        labels = _json_get(obj, "metadata.labels", {}) or {}
        tpl_spec = _json_get(obj, "spec.template.spec", {}) or {}

        replicas_desired = None
        replicas_ready = None
        job_status: Optional[Dict[str, Any]] = None
        if kind in {"Deployment", "StatefulSet"}:
            replicas_desired = _safe_int(_json_get(obj, "spec.replicas", 0)) or 0
            # readyReplicas for deployments/statefulsets
            replicas_ready = _safe_int(_json_get(obj, "status.readyReplicas", 0)) or 0

        if kind == "Job":
            # Jobs don't have replicas; track active/succeeded/failed.
            replicas_desired = None
            replicas_ready = None
            job_status = {
                "active": _safe_int(_json_get(obj, "status.active", 0)) or 0,
                "succeeded": _safe_int(_json_get(obj, "status.succeeded", 0)) or 0,
                "failed": _safe_int(_json_get(obj, "status.failed", 0)) or 0,
                "start_time": _json_get(obj, "status.startTime", None),
                "completion_time": _json_get(obj, "status.completionTime", None),
            }

        pod_counts = _summarize_pods_for_workload(uid, pods, pod_owner) if uid else {}
        pod_summary = ", ".join([f"{k}={v}" for k, v in pod_counts.items() if v]) or "unknown"

        images = _images_for_containers(tpl_spec) if tpl_spec else []
        observed_digests = _observed_image_digests_for_workload(uid, pods, pod_owner) if (uid and pods) else {}
        resources = _resources_for_containers(tpl_spec) if tpl_spec else {"containers": {}, "initContainers": {}}
        env_summary = _env_summary_for_containers(tpl_spec) if tpl_spec else {k: {"present": False, "value": None} for k in ENV_KEYS_OF_INTEREST}

        allowed, allowed_reason = _allowed_to_run(env_summary)

        svc = svc_by_instance.get(name)
        health_block: Dict[str, Any] = {"cluster_dns_url": "unknown", "samples": []}
        if svc:
            health_block["cluster_dns_url"] = _service_dns_url(svc)

        workloads_out.append(
            {
                "workload_name": name,
                "kind": kind,
                "namespace": namespace,
                "labels": labels,
                "replicas_desired": replicas_desired,
                "replicas_ready": replicas_ready,
                "pod_status_summary": pod_summary,
                "images": images,
                "observed_image_digests": observed_digests,
                "service_account": str(tpl_spec.get("serviceAccountName") or "default") if tpl_spec else "unknown",
                "resources": resources,
                "env_summary": env_summary,
                "allowed_to_run": allowed,
                "allowed_reason": allowed_reason,
                "job_status": job_status,
                "health": health_block,
                "_uid": uid,
            }
        )

    for d in deployments:
        add_workload("Deployment", d)
    for s in statefulsets:
        add_workload("StatefulSet", s)
    for j in jobs:
        add_workload("Job", j)

    # Health sampling (services only)
    if meta.get("cluster_access") and not args.skip_health and services:
        for w in workloads_out:
            inst = w.get("workload_name")
            svc = svc_by_instance.get(inst)
            if not svc:
                continue
            sp = _service_port(svc)
            if not sp:
                continue
            name = str(_json_get(svc, "metadata.name", ""))

            # Required probes: /healthz + /heartbeat (marketdata)
            probe_paths = ["/healthz"]
            component = str((w.get("labels") or {}).get("app.kubernetes.io/component") or "")
            if component == "marketdata" or "marketdata" in (inst or "").lower():
                probe_paths.append("/heartbeat")

            # Compatibility fallback: many services use /health
            probe_paths.append("/health")

            samples = _port_forward_and_probe(
                args.context,
                namespace,
                name,
                sp,
                probe_paths=probe_paths,
                timeout_s_per_path=2.0,
            )
            w["health"]["samples"] = [
                {"path": s.path, "ok": s.ok, "status_code": s.status_code, "excerpt": s.excerpt, "error": s.error}
                for s in samples
            ]

    # Compute issues + summary
    top_issues: List[Dict[str, str]] = []
    healthy = 0
    degraded = 0
    halted = 0

    def add_issue(workload: str, issue: str) -> None:
        top_issues.append({"workload": workload, "issue": issue})

    for w in workloads_out:
        wl = f"{w.get('kind')}/{w.get('workload_name')}"
        if not w.get("allowed_to_run"):
            halted += 1
            add_issue(wl, f"Not allowed to run: {w.get('allowed_reason')}")

        ps = str(w.get("pod_status_summary") or "")
        if "crashloop=" in ps or "imagepull=" in ps:
            if "crashloop=" in ps:
                add_issue(wl, "CrashLoop detected in pod statuses")
            if "imagepull=" in ps:
                add_issue(wl, "ImagePullBackOff/ErrImagePull detected in pod statuses")

        # Missing env keys
        envs = w.get("env_summary") or {}
        missing = [k for k in ENV_KEYS_OF_INTEREST if not (envs.get(k) or {}).get("present")]
        # Don't require KILL_SWITCH to exist everywhere; it's optional.
        missing = [k for k in missing if k != "KILL_SWITCH"]
        if missing:
            add_issue(wl, f"Missing env vars: {', '.join(missing)}")

        # Health sampling: ok if any healthz/health is ok
        samples = (w.get("health") or {}).get("samples") or []
        ok_any = any((s.get("path") in {"/healthz", "/health"} and s.get("ok")) for s in samples)
        fail_health = bool(samples) and not ok_any
        if fail_health:
            add_issue(wl, "Health check failed (no successful /healthz or /health response)")
            degraded += 1
        else:
            # If replicas not ready -> degraded
            if w.get("replicas_desired") is not None and (w.get("replicas_ready") or 0) < (w.get("replicas_desired") or 0):
                degraded += 1
                add_issue(wl, "Not all replicas are ready")
            else:
                healthy += 1

    # Deterministic recommended actions (small set)
    recommended: List[str] = []
    if meta.get("cluster_access") is False:
        recommended.append("Ensure kubectl is installed and configured to reach the cluster (context + RBAC).")
    if any("ImagePull" in i.get("issue", "") for i in top_issues):
        recommended.append("Verify Artifact Registry image tag/digest exists and nodes have pull permission (Workload Identity / node SA).")
    if any("CrashLoop" in i.get("issue", "") for i in top_issues):
        recommended.append("Inspect logs for crashing pods and verify required env/config is present; avoid changing strategy logic.")
    if any("Missing env vars" in i.get("issue", "") for i in top_issues):
        recommended.append("Add missing non-secret env vars (REPO_ID/AGENT_*) to the workload specs; keep secrets in Secret refs.")
    if any("Not allowed to run" in i.get("issue", "") for i in top_issues):
        recommended.append("If workloads should run, confirm KILL_SWITCH/AGENT_MODE is intentionally set; do not enable trading unintentionally.")
    if not recommended:
        recommended.append("No immediate action required; continue monitoring readiness + health endpoints.")

    summary = {
        "workloads_total": len(workloads_out),
        "deployments": len(deployments),
        "statefulsets": len(statefulsets),
        "jobs": len(jobs),
        "jobs_active": sum(int((_json_get(j, "status.active", 0) or 0)) for j in jobs),
        "healthy": healthy,
        "degraded": degraded,
        "halted": halted,
    }

    report: Dict[str, Any] = {
        "meta": meta,
        "summary": summary,
        "workloads": [
            {k: v for k, v in w.items() if not k.startswith("_")}
            for w in sorted(workloads_out, key=lambda x: (x.get("kind", ""), x.get("workload_name", "")))
        ],
        "services": [
            {
                "name": _json_get(s, "metadata.name", ""),
                "namespace": _json_get(s, "metadata.namespace", ""),
                "type": _json_get(s, "spec.type", ""),
                "cluster_ip": _json_get(s, "spec.clusterIP", ""),
                "ports": _json_get(s, "spec.ports", []),
                "labels": _json_get(s, "metadata.labels", {}),
            }
            for s in sorted(services, key=lambda x: _json_get(x, "metadata.name", ""))
        ],
        "top_issues": top_issues[:25],
        "recommended_actions": recommended,
        "errors": errors[:25],
    }

    md = _mk_markdown(report)
    md_path = output_dir / "deploy_report.md"
    json_path = output_dir / "deploy_report.json"
    md_path.write_text(md, encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    # Always succeed; degraded reports are still useful.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

