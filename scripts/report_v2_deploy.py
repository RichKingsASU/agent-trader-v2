#!/usr/bin/env python3
"""
Generate an auditable, best-effort deploy report for CI.

Requirements:
- Always produce both:
  - audit_artifacts/deploy_report.md
  - audit_artifacts/deploy_report.json
- If cluster is unreachable (or kubectl missing), report must still explain why.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ART_DIR = REPO_ROOT / "audit_artifacts"
MD_PATH = ART_DIR / "deploy_report.md"
JSON_PATH = ART_DIR / "deploy_report.json"


def _run(cmd: list[str], timeout_s: int = 15) -> dict:
    try:
        p = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        return {
            "ok": p.returncode == 0,
            "returncode": p.returncode,
            "stdout": (p.stdout or "").strip(),
            "stderr": (p.stderr or "").strip(),
        }
    except FileNotFoundError as e:
        return {"ok": False, "returncode": None, "stdout": "", "stderr": str(e)}
    except Exception as e:  # best-effort reporting
        return {"ok": False, "returncode": None, "stdout": "", "stderr": repr(e)}


def _env(key: str) -> str | None:
    v = os.getenv(key)
    return v if v else None


def _git_rev() -> dict:
    return {
        "sha": _env("GITHUB_SHA") or _env("CI_COMMIT_SHA") or None,
        "ref": _env("GITHUB_REF") or None,
        "repository": _env("GITHUB_REPOSITORY") or None,
        "workflow": _env("GITHUB_WORKFLOW") or None,
        "run_id": _env("GITHUB_RUN_ID") or None,
        "run_attempt": _env("GITHUB_RUN_ATTEMPT") or None,
        "event_name": _env("GITHUB_EVENT_NAME") or None,
    }


def _list_k8s_files() -> list[str]:
    k8s_dir = REPO_ROOT / "k8s"
    if not k8s_dir.exists():
        return []
    out: list[str] = []
    for p in sorted(k8s_dir.rglob("*.y*ml")):
        # keep paths stable/relative
        try:
            out.append(str(p.relative_to(REPO_ROOT)))
        except Exception:
            out.append(str(p))
    return out


def main() -> int:
    ART_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat()
    git = _git_rev()

    kubectl_version = _run(["kubectl", "version", "--client=true", "--output=json"])
    kubectl_current_context = _run(["kubectl", "config", "current-context"])
    kubectl_cluster_info = _run(["kubectl", "cluster-info"])

    cluster_reachable = bool(kubectl_cluster_info["ok"])
    cluster_reason = None
    if not cluster_reachable:
        # Prefer a clear failure reason.
        cluster_reason = (
            kubectl_cluster_info["stderr"]
            or kubectl_cluster_info["stdout"]
            or "kubectl cluster-info failed"
        )

    report = {
        "schema_version": "v2.deploy_report/1",
        "generated_at_utc": now,
        "git": git,
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "kubernetes": {
            "kubectl_client_version": kubectl_version if kubectl_version["ok"] else kubectl_version,
            "current_context": kubectl_current_context if kubectl_current_context["ok"] else kubectl_current_context,
            "cluster_info": kubectl_cluster_info if kubectl_cluster_info["ok"] else kubectl_cluster_info,
            "cluster_reachable": cluster_reachable,
            "cluster_unreachable_reason": cluster_reason,
        },
        "manifests": {
            "k8s_dir_present": (REPO_ROOT / "k8s").exists(),
            "k8s_files": _list_k8s_files(),
        },
        "notes": {
            "purpose": "CI/CD institutional gate deploy report (dry-run validation + audit artifact).",
            "safety": "This report does not deploy. CI also enforces that k8s manifests do not contain ':latest' or 'AGENT_MODE=EXECUTE'.",
        },
    }

    # Write JSON (stable formatting for diffs)
    JSON_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Write Markdown (human-readable)
    md_lines = []
    md_lines.append("# AgentTrader v2 — Deploy Dry-Run Report (CI Artifact)")
    md_lines.append("")
    md_lines.append("## Summary")
    md_lines.append(f"- Generated (UTC): `{now}`")
    md_lines.append(f"- Repo: `{git.get('repository') or 'unknown'}`")
    md_lines.append(f"- Ref: `{git.get('ref') or 'unknown'}`")
    md_lines.append(f"- SHA: `{git.get('sha') or 'unknown'}`")
    md_lines.append(f"- Workflow: `{git.get('workflow') or 'unknown'}` (run `{git.get('run_id') or 'unknown'}` attempt `{git.get('run_attempt') or 'unknown'}`)")
    md_lines.append("")
    md_lines.append("## Kubernetes connectivity")
    md_lines.append(f"- Cluster reachable: `{str(cluster_reachable).lower()}`")
    if cluster_reachable:
        md_lines.append(f"- Current context: `{kubectl_current_context.get('stdout') or 'unknown'}`")
    else:
        md_lines.append("- Reason:")
        md_lines.append("")
        md_lines.append("```")
        md_lines.append(cluster_reason or "unknown")
        md_lines.append("```")
    md_lines.append("")
    md_lines.append("## Manifests scanned")
    k8s_files = report["manifests"]["k8s_files"]
    md_lines.append(f"- `k8s/` present: `{str(report['manifests']['k8s_dir_present']).lower()}`")
    md_lines.append(f"- Manifest file count: `{len(k8s_files)}`")
    if k8s_files:
        md_lines.append("")
        for p in k8s_files:
            md_lines.append(f"- `{p}`")
    md_lines.append("")
    md_lines.append("## Artifact outputs")
    md_lines.append(f"- `{MD_PATH.relative_to(REPO_ROOT)}`")
    md_lines.append(f"- `{JSON_PATH.relative_to(REPO_ROOT)}`")
    md_lines.append("")
    md_lines.append("## Safety")
    md_lines.append("- CI is configured to fail closed on unsafe k8s configs (e.g., forbidden `:latest`, forbidden `AGENT_MODE=EXECUTE`, missing required identity env vars/labels).")
    md_lines.append("")

    MD_PATH.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

