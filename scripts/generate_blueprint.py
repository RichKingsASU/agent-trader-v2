#!/usr/bin/env python3
"""
AgentTrader v2 — Repo Blueprint Generator

Deterministic, local-only scanner that emits:
  - docs/BLUEPRINT.md
  - audit_artifacts/blueprints/BLUEPRINT_<YYYYMMDD_HHMM>.md

Rules:
  - No network calls.
  - If something can't be detected, report "unknown" (do not guess).
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ID_DEFAULT = "RichKingsASU/agent-trader-v2"

K8S_WORKLOAD_KINDS = {"Deployment", "StatefulSet", "Job", "CronJob"}
K8S_SERVICE_KINDS = {"Service"}

SAFE_ENV_NAME_RE = re.compile(r"^(AGENT_|EXECUTION_|DRY_RUN$|SHADOW_|TENANT_|MARKETDATA_).+|^(AGENT_ROLE|AGENT_MODE|DRY_RUN|EXECUTION_HALTED)$")
SENSITIVE_NAME_RE = re.compile(r"(SECRET|TOKEN|PASSWORD|PASS|KEY|CREDENTIAL|PRIVATE)", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class HealthEndpoint:
    probe: str  # readiness|liveness|startup
    kind: str  # http|tcp|exec|unknown
    detail: str


@dataclasses.dataclass(frozen=True)
class Component:
    name: str
    kind: str  # deploy|sts|job|cronjob|unknown
    namespace: str
    image: str
    agent_role: str
    agent_mode: str
    health_endpoints: tuple[str, ...]
    k8s_path: str
    gaps: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class BuildPipeline:
    path: str
    images: tuple[str, ...]


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _try_yaml_load_all(text: str) -> list[Any]:
    """
    Attempts to parse YAML documents via PyYAML if present.
    Falls back to an empty list (caller may do regex-based extraction).
    """
    try:
        import yaml  # type: ignore
    except Exception:
        return []
    try:
        docs = list(yaml.safe_load_all(text))
        return [d for d in docs if d is not None]
    except Exception:
        return []


def _git_sha(repo_root: Path) -> str:
    try:
        out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_root))
        return out.decode("utf-8", errors="replace").strip()
    except Exception:
        return "unknown"


def _mkdirp(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _rel(repo_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except Exception:
        return str(path)


def _norm_kind(kind: str) -> str:
    k = (kind or "").strip()
    return {
        "Deployment": "deploy",
        "StatefulSet": "sts",
        "Job": "job",
        "CronJob": "cronjob",
        "Service": "service",
    }.get(k, "unknown")


def _get(d: Any, path: str, default: Any = None) -> Any:
    """
    Safe nested-get for dict-like objects using dot paths.
    """
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        if part not in cur:
            return default
        cur = cur[part]
    return cur


def _as_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def _env_value_repr(env_item: dict[str, Any]) -> str:
    """
    Represents env var default without leaking secrets.
    """
    name = str(env_item.get("name") or "")
    if "value" in env_item:
        raw = "" if env_item.get("value") is None else str(env_item.get("value"))
        if SENSITIVE_NAME_RE.search(name):
            return "<redacted>"
        if raw == "":
            # Empty literal default is meaningful (e.g., placeholders), but keep safe.
            return '""'
        return raw
    if "valueFrom" in env_item:
        # We don't dereference anything; just note source kind.
        vf = env_item.get("valueFrom") or {}
        if isinstance(vf, dict):
            if "secretKeyRef" in vf:
                return "<from secret>"
            if "configMapKeyRef" in vf:
                return "<from configmap>"
            if "fieldRef" in vf:
                return "<from fieldRef>"
        return "<from valueFrom>"
    return "unknown"


def _extract_probe_endpoints(container: dict[str, Any]) -> list[HealthEndpoint]:
    endpoints: list[HealthEndpoint] = []
    for probe_name in ("readinessProbe", "livenessProbe", "startupProbe"):
        p = container.get(probe_name)
        if not isinstance(p, dict):
            continue
        if isinstance(p.get("httpGet"), dict):
            http = p["httpGet"]
            path = str(http.get("path") or "unknown")
            port = http.get("port")
            endpoints.append(HealthEndpoint(probe=probe_name.replace("Probe", ""), kind="http", detail=f"GET {path} port {port}"))
        elif isinstance(p.get("tcpSocket"), dict):
            tcp = p["tcpSocket"]
            port = tcp.get("port")
            endpoints.append(HealthEndpoint(probe=probe_name.replace("Probe", ""), kind="tcp", detail=f"TCP port {port}"))
        elif isinstance(p.get("exec"), dict):
            cmd = p["exec"].get("command")
            endpoints.append(HealthEndpoint(probe=probe_name.replace("Probe", ""), kind="exec", detail=f"exec {cmd!r}"))
        else:
            endpoints.append(HealthEndpoint(probe=probe_name.replace("Probe", ""), kind="unknown", detail="unknown"))
    return endpoints


def scan_k8s_components(repo_root: Path) -> tuple[list[Component], list[str]]:
    k8s_dir = repo_root / "k8s"
    gaps: list[str] = []
    components: list[Component] = []
    if not k8s_dir.exists():
        return components, ["missing k8s/ directory"]

    yaml_files = sorted([p for p in k8s_dir.rglob("*.yaml") if p.is_file()])
    for path in yaml_files:
        text = _read_text(path)
        docs = _try_yaml_load_all(text)
        if not docs:
            # If YAML parsing isn't available, we still include a minimal placeholder.
            continue

        for doc in docs:
            if not isinstance(doc, dict):
                continue
            kind = str(doc.get("kind") or "")
            if kind not in K8S_WORKLOAD_KINDS:
                continue

            name = str(_get(doc, "metadata.name", "unknown"))
            ns = str(_get(doc, "metadata.namespace", "default"))
            spec_tpl = None
            if kind == "CronJob":
                spec_tpl = _get(doc, "spec.jobTemplate.spec.template", {})
            else:
                spec_tpl = _get(doc, "spec.template", {})
            pod_spec = _get(spec_tpl, "spec", {}) if isinstance(spec_tpl, dict) else {}
            containers = _as_list(_get(pod_spec, "containers", []))
            c0 = containers[0] if containers else {}
            if not isinstance(c0, dict):
                c0 = {}

            image = str(c0.get("image") or "unknown")
            env_items = [e for e in _as_list(c0.get("env")) if isinstance(e, dict)]
            env_map: dict[str, str] = {}
            for e in env_items:
                env_name = str(e.get("name") or "")
                if not env_name:
                    continue
                if not SAFE_ENV_NAME_RE.match(env_name):
                    continue
                env_map[env_name] = _env_value_repr(e)

            agent_role = env_map.get("AGENT_ROLE", "unknown")
            agent_mode = env_map.get("AGENT_MODE", "unknown")

            endpoints = _extract_probe_endpoints(c0)
            endpoint_strs = tuple(
                sorted(
                    {f"{ep.probe}: {ep.kind} {ep.detail}" for ep in endpoints},
                    key=lambda s: (s.split(":")[0], s),
                )
            )

            component_gaps: list[str] = []
            has_readiness = any(ep.probe == "readiness" for ep in endpoints)
            has_liveness = any(ep.probe == "liveness" for ep in endpoints)
            if not has_readiness or not has_liveness:
                component_gaps.append("missing probes (readiness/liveness)")
            if agent_role == "unknown" and agent_mode == "unknown":
                component_gaps.append("missing AGENT_ROLE/AGENT_MODE env defaults")
            if "EXECUTION_HALTED" not in env_map:
                component_gaps.append("missing EXECUTION_HALTED kill-switch wiring")
            if ":latest" in image or image.endswith(":latest"):
                component_gaps.append("image uses :latest")
            if image != "unknown" and ":" not in image.split("/")[-1]:
                component_gaps.append("image tag not pinned")

            components.append(
                Component(
                    name=name,
                    kind=_norm_kind(kind),
                    namespace=ns,
                    image=image,
                    agent_role=agent_role,
                    agent_mode=agent_mode,
                    health_endpoints=endpoint_strs if endpoint_strs else ("unknown",),
                    k8s_path=_rel(repo_root, path),
                    gaps=tuple(sorted(set(component_gaps))),
                )
            )

    # Deterministic ordering
    components.sort(key=lambda c: (c.namespace, c.name, c.kind))
    return components, gaps


def scan_k8s_services(repo_root: Path) -> list[dict[str, str]]:
    """
    Services are not part of the required component inventory table, but we use
    them to enrich "health endpoints" and deployment topology context.
    """
    k8s_dir = repo_root / "k8s"
    services: list[dict[str, str]] = []
    if not k8s_dir.exists():
        return services
    yaml_files = sorted([p for p in k8s_dir.rglob("*.yaml") if p.is_file()])
    for path in yaml_files:
        docs = _try_yaml_load_all(_read_text(path))
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if str(doc.get("kind") or "") not in K8S_SERVICE_KINDS:
                continue
            name = str(_get(doc, "metadata.name", "unknown"))
            ns = str(_get(doc, "metadata.namespace", "default"))
            ports = _as_list(_get(doc, "spec.ports", []))
            ports_s: list[str] = []
            for p in ports:
                if not isinstance(p, dict):
                    continue
                ports_s.append(f"{p.get('port')}->{p.get('targetPort')}")
            services.append(
                {
                    "name": name,
                    "namespace": ns,
                    "ports": ", ".join(ports_s) if ports_s else "unknown",
                    "path": _rel(repo_root, path),
                }
            )
    services.sort(key=lambda s: (s["namespace"], s["name"]))
    return services


def scan_cloudbuild_pipelines(repo_root: Path) -> list[BuildPipeline]:
    paths = sorted([p for p in repo_root.rglob("cloudbuild*.yaml") if p.is_file()])
    pipelines: list[BuildPipeline] = []
    for path in paths:
        docs = _try_yaml_load_all(_read_text(path))
        doc = docs[0] if docs else None
        images: list[str] = []
        if isinstance(doc, dict):
            imgs = doc.get("images")
            if isinstance(imgs, list):
                images = [str(i) for i in imgs if i is not None]
        pipelines.append(BuildPipeline(path=_rel(repo_root, path), images=tuple(images) if images else ("unknown",)))
    pipelines.sort(key=lambda p: p.path)
    return pipelines


def scan_docs_links(repo_root: Path) -> list[str]:
    docs_dir = repo_root / "docs"
    if not docs_dir.exists():
        return []
    md_paths = sorted([p for p in docs_dir.rglob("*.md") if p.is_file()])
    links = [_rel(repo_root, p) for p in md_paths]
    return links


def infer_logical_components(repo_root: Path) -> dict[str, list[str]]:
    """
    Infer major logical subsystems from backend layout without guessing.
    We only use file paths and a small set of stable directory names.
    """
    backend = repo_root / "backend"
    out: dict[str, list[str]] = {"mission-control": [], "marketdata": [], "strategy": [], "execution": []}
    if not backend.exists():
        return out

    # Deterministic: check known directories/files, do not walk entire tree deeply.
    candidates = [
        "app.py",
        "strategy_engine",
        "strategy_runner",
        "strategy_service",
        "execution",
        "services/execution_service",
        "marketdata",
        "ingestion",
        "risk",
        "risk_service",
        "tenancy",
        "messaging",
    ]
    for rel in candidates:
        p = backend / rel
        if not p.exists():
            continue
        r = _rel(repo_root, p)
        if "execution" in rel:
            out["execution"].append(r)
        elif "marketdata" in rel or "ingestion" in rel:
            out["marketdata"].append(r)
        elif "strategy" in rel:
            out["strategy"].append(r)
        else:
            out["mission-control"].append(r)

    for k in out:
        out[k] = sorted(set(out[k]))
    return out


def _detect_marketdata_freshness_gating(repo_root: Path) -> str:
    p = repo_root / "backend" / "execution" / "marketdata_health.py"
    if not p.exists():
        return "unknown"
    text = _read_text(p)
    if "stale_threshold_seconds" in text and "is_stale" in text and "market_ingest" in text:
        return "present (backend/execution/marketdata_health.py: heartbeat staleness check)"
    return "unknown"


def infer_known_gaps(
    *,
    repo_root: Path,
    components: list[Component],
    pipelines: list[BuildPipeline],
    k8s_scan_gaps: list[str],
    docs_links: list[str],
) -> list[str]:
    gaps: list[str] = []
    gaps.extend(k8s_scan_gaps)

    # Component-derived gaps
    for c in components:
        for g in c.gaps:
            gaps.append(f"{c.namespace}/{c.name}: {g}")

    # Docs gaps (minimal, deterministic)
    required_docs = [
        "docs/KILL_SWITCH.md",
        "docs/MARKETDATA_HEALTH_CONTRACT.md",
        "docs/ZERO_TRUST_AGENT_IDENTITY.md",
        "docs/PROD_READINESS_CHECKLIST.md",
        "docs/ops/reporting.md",
        "docs/ops/README.md",
    ]
    link_set = set(docs_links)
    for req in required_docs:
        if req not in link_set:
            gaps.append(f"missing docs: {req}")

    # Any :latest references in build pipelines
    for p in pipelines:
        for img in p.images:
            if ":latest" in (img or ""):
                gaps.append(f"{p.path}: build pipeline references :latest ({img})")

    # YAML parsing availability
    try:
        import yaml  # type: ignore  # noqa: F401
    except Exception:
        gaps.append("PyYAML not available: k8s/cloudbuild parsing may be incomplete")

    return sorted(set(gaps))


def _md_escape(s: str) -> str:
    return s.replace("|", r"\|").strip()


def render_blueprint_md(
    *,
    repo_root: Path,
    repo_id: str,
    git_sha: str,
    generated_at_utc: dt.datetime,
    components: list[Component],
    services: list[dict[str, str]],
    pipelines: list[BuildPipeline],
    docs_links: list[str],
    logical_components: dict[str, list[str]],
    known_gaps: list[str],
) -> str:
    gen_iso = generated_at_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    # Safety posture signals (deterministic extraction from components/env defaults)
    kill_switch_wired = any(
        c for c in components if "missing EXECUTION_HALTED kill-switch wiring" not in c.gaps
    )

    # Prefer explicit check: any component has EXECUTION_HALTED wired via env map => we counted as not missing.
    # If no components, mark unknown.
    if not components:
        halted_note = "unknown (no k8s workloads detected)"
    else:
        halted_note = "present (k8s manifests wire EXECUTION_HALTED via ConfigMap)" if kill_switch_wired else "unknown"

    # Component table
    comp_rows: list[str] = []
    for c in components:
        role_mode = f"AGENT_ROLE={c.agent_role}; AGENT_MODE={c.agent_mode}"
        comp_rows.append(
            "| "
            + " | ".join(
                [
                    _md_escape(c.name),
                    _md_escape(c.kind),
                    _md_escape(c.image),
                    _md_escape(role_mode),
                    _md_escape("; ".join(c.health_endpoints) if c.health_endpoints else "unknown"),
                ]
            )
            + " |"
        )

    # Build table
    pipe_rows: list[str] = []
    for p in pipelines:
        pipe_rows.append("| " + " | ".join([_md_escape(p.path), _md_escape(", ".join(p.images))]) + " |")

    # Docs index
    docs_lines: list[str] = []
    for rel in docs_links:
        docs_lines.append(f"- `{rel}`")

    # Ops commands: prefer repo scripts; keep deterministic and local-safe.
    ops_cmds: list[str] = []
    if (repo_root / "scripts" / "deploy_v2.sh").exists():
        ops_cmds.append("```bash\n./scripts/deploy_v2.sh\n```")
    else:
        ops_cmds.append("```bash\n# unknown (scripts/deploy_v2.sh not found)\n```")
    if (repo_root / "scripts" / "report_v2_deploy.sh").exists():
        ops_cmds.append("```bash\n./scripts/report_v2_deploy.sh\n```")
    elif (repo_root / "scripts" / "deploy_report.sh").exists():
        ops_cmds.append("```bash\n./scripts/deploy_report.sh\n```")
    else:
        ops_cmds.append("```bash\n# unknown (no deploy report script detected)\n```")

    # Readiness + logs: derive from k8s workloads if present.
    if components:
        ns = components[0].namespace
        ops_cmds.append(f"```bash\nkubectl -n {ns} get pods\nkubectl -n {ns} get deploy,sts,job,cronjob\n```")
        for c in components:
            if c.kind in ("deploy", "sts"):
                ops_cmds.append(f"```bash\nkubectl -n {c.namespace} rollout status {c.kind}/{c.name}\n```")
        for c in components:
            ops_cmds.append(f"```bash\nkubectl -n {c.namespace} logs -l app.kubernetes.io/instance={c.name} --tail=200\n```")
    else:
        ops_cmds.append("```bash\n# unknown (no k8s components detected)\n```")

    # Safety controls section items
    freshness = _detect_marketdata_freshness_gating(repo_root)
    safety_lines = [
        f"- **Kill-switch**: {halted_note} (see `docs/KILL_SWITCH.md`, `k8s/05-kill-switch-configmap.yaml`).",
        f"- **Marketdata freshness gating**: {freshness}.",
        "- **Agent identity + intent logging**: documented (see `docs/ZERO_TRUST_AGENT_IDENTITY.md`; generator does not infer runtime settings).",
    ]

    # Topology context
    svc_lines: list[str] = []
    if services:
        svc_lines.append("| service | namespace | ports | manifest |")
        svc_lines.append("|---|---|---|---|")
        for s in services:
            svc_lines.append(f"| `{s['name']}` | `{s['namespace']}` | `{_md_escape(s['ports'])}` | `{s['path']}` |")
    else:
        svc_lines.append("- `unknown` (no Services detected in k8s manifests)")

    # Logical components summary
    logical_lines: list[str] = []
    for k in ("mission-control", "marketdata", "strategy", "execution"):
        items = logical_components.get(k) or []
        if items:
            logical_lines.append(f"- **{k}**: " + ", ".join(f"`{p}`" for p in items))
        else:
            logical_lines.append(f"- **{k}**: unknown")

    gaps_lines = "\n".join(f"- {g}" for g in known_gaps) if known_gaps else "- (none detected)"

    md = """
# Blueprint (autogenerated)

**Generated:** {now_str}
**Git SHA:** {sha}
**Python:** {py_version}
**Repo root:** `{repo_root}`

## High-level packages

{pkg_lines_str}

## Top-level files

{file_lines_str}

## K8s Components

{k8s_lines}

## K8s Services

{svc_lines}

## Cloud Build Pipelines

| cloudbuild file | image output |
|---|---|
{pipe_rows_str}

## Safety Controls

{safety_lines}

## Ops Commands

### deploy

{ops_cmd_deploy}

### report

{ops_cmd_report}

### readiness

{ops_cmd_readiness}

### logs

{ops_cmd_logs}

## Known Gaps (automatically inferred)

{gaps_lines}

## Links (docs index)

{docs_lines_str}
""".format(
        now_str=now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        sha=sha,
        py_version=sys.version.split()[0],
        repo_root=repo_root,
        pkg_lines_str=os.linesep.join(pkg_lines),
        file_lines_str=os.linesep.join(file_lines),
        k8s_lines=os.linesep.join(k8s_lines) if k8s_lines else "no k8s components found",
        svc_lines=os.linesep.join(svc_lines) if svc_lines else "no k8s services found",
        pipe_rows_str=os.linesep.join(pipe_rows) if pipe_rows else '| unknown | unknown |',
        safety_lines=os.linesep.join(safety_lines),
        ops_cmd_deploy=ops_cmds[0],
        ops_cmd_report=ops_cmds[1],
        ops_cmd_readiness=ops_cmds[2] if len(ops_cmds) > 2 else "```bash\n# unknown\n```",
        ops_cmd_logs=os.linesep.join(ops_cmds[3:]) if len(ops_cmds) > 3 else "```bash\n# unknown\n```",
        gaps_lines=gaps_lines,
        docs_lines_str=os.linesep.join(docs_lines) if docs_lines else "- `docs/` not found",
    )
    return md


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Generate docs/BLUEPRINT.md and audit copy.")
    ap.add_argument("--repo-id", default=REPO_ID_DEFAULT, help="Repo identifier to embed (default: %(default)s)")
    ap.add_argument("--quiet", action="store_true", help="Suppress non-error prints")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    generated_at = _utc_now()
    ts = generated_at.strftime("%Y%m%d_%H%M")

    git_sha = _git_sha(repo_root)

    components, k8s_scan_gaps = scan_k8s_components(repo_root)
    services = scan_k8s_services(repo_root)
    pipelines = scan_cloudbuild_pipelines(repo_root)
    docs_links = scan_docs_links(repo_root)
    logical = infer_logical_components(repo_root)

    known_gaps = infer_known_gaps(
        repo_root=repo_root,
        components=components,
        pipelines=pipelines,
        k8s_scan_gaps=k8s_scan_gaps,
        docs_links=docs_links,
    )

    md = render_blueprint_md(
        repo_root=repo_root,
        repo_id=args.repo_id,
        git_sha=git_sha,
        generated_at_utc=generated_at,
        components=components,
        services=services,
        pipelines=pipelines,
        docs_links=docs_links,
        logical_components=logical,
        known_gaps=known_gaps,
    )

    docs_out = repo_root / "docs" / "BLUEPRINT.md"
    audit_out_dir = repo_root / "audit_artifacts" / "blueprints"
    audit_out = audit_out_dir / f"BLUEPRINT_{ts}.md"

    _mkdirp(docs_out.parent)
    _mkdirp(audit_out_dir)

    docs_out.write_text(md, encoding="utf-8")
    audit_out.write_text(md, encoding="utf-8")

    if not args.quiet:
        print(f"Wrote: {docs_out}")
        print(f"Wrote: {audit_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

