#!/usr/bin/env python3
"""
CI Guardrail Enforcement (read-only).

This script is intentionally strict and deterministic. It scans *tracked* files
(`git ls-files`) to avoid noise from local virtualenvs/build artifacts.

Guardrails enforced (FAIL if any triggered):
- sys.path is mutated (runtime/service code scope)
- Flask dev server is used (app.run / flask run)
- `python main.py` is used (runtime command/config scope)
- gunicorn is missing when a runtime service uses gunicorn

Notes:
- We intentionally do not refactor any code; this is enforcement only.
- Scope is focused on runtime services/configs (containers + deploy scripts), not
  ad-hoc developer scripts or unit tests.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


RE_SYS_PATH_MUTATION = re.compile(
    r"""
    \b
    sys\.path
    (?:
        \s*(?:\+=|=)              # sys.path += ... OR sys.path = ...
        |
        \s*\.\s*(?:append|insert|extend|remove|pop)\s*\(   # sys.path.append(
    )
    """,
    re.VERBOSE,
)

RE_FLASK_DEV_SERVER = re.compile(
    r"""
    (?:
        ^\s*(?:app|application)\.run\s*\(      # app.run(
        |
        \bFlask\([^\n]*\)\.run\s*\(            # Flask(...).run(
        |
        \bflask\s+run\b                        # `flask run` command
    )
    """,
    re.VERBOSE | re.MULTILINE,
)

# Matches both shell-ish and Docker JSON-array-ish forms.
RE_PYTHON_MAIN_DOT_PY = re.compile(
    r"""
    (?:
        \bpython(?:3(?:\.\d+)?)?\s+(?:-[^\n]+\s+)*(\./)?main\.py\b
        |
        \["python(?:3)?",\s*"main\.py"\]
        |
        \["python(?:3)?",\s*"\./main\.py"\]
    )
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int
    excerpt: str


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
        if out:
            return Path(out)
    except Exception:
        pass
    return Path.cwd()


def _git_tracked_files(repo: Path) -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], cwd=str(repo), text=True)
    files: list[Path] = []
    for line in out.splitlines():
        raw = line.strip()
        if not raw:
            continue
        # Important: do NOT resolve() symlinks here; a tracked symlink can point
        # outside the repo and would break runtime-scope checks.
        p = (repo / raw)
        try:
            _ = p.relative_to(repo)
        except Exception:
            continue
        if p.exists() and p.is_file():
            files.append(p)
    return files


def _is_runtime_scope(path: Path, repo: Path) -> bool:
    """
    Scope guardrails to runtime services/configs:
    - Containerized services: cloudrun_*, backend/* (service dirs), infra Dockerfiles
    - Deploy/config: infra/, k8s/, ops/
    """
    try:
        rel = str(path.relative_to(repo)).replace("\\", "/")
    except Exception:
        return False

    # Exclude non-runtime / developer-only scopes.
    if rel.startswith(("tests/", "docs/", "audit_artifacts/")):
        return False
    if rel.startswith("scripts/") and not rel.startswith(("scripts/ci/", "scripts/deploy", "scripts/cloudrun", "scripts/k8s")):
        return False
    if "/tests/" in rel or rel.endswith(("_test.py", "test.py")) or "/examples/" in rel:
        return False

    # Runtime scopes.
    if rel.startswith(("cloudrun_consumer/", "cloudrun_ingestor/")):
        return True
    if rel.startswith(("infra/", "k8s/", "ops/")):
        return True
    if rel.startswith("backend/"):
        # backend is a mix of libs + services; still treat as runtime scope
        # but exclude known non-runtime example trees.
        if rel.startswith("backend/strategy_runner/examples/"):
            return False
        return True

    return False


def _is_text_candidate(path: Path) -> bool:
    name = path.name
    if name.startswith("."):
        # still allow dotfiles like .dockerignore etc.
        return True
    if name == "Dockerfile" or name.startswith("Dockerfile"):
        return True
    return path.suffix.lower() in {".py", ".sh", ".md", ".yml", ".yaml", ".txt"}


def _read_text(path: Path) -> str:
    # Keep deterministic and safe even on odd encodings.
    return path.read_text(encoding="utf-8", errors="replace")


def _find_regex(rule: str, path: Path, text: str, regex: re.Pattern[str]) -> list[Finding]:
    findings: list[Finding] = []
    for i, line in enumerate(text.splitlines(), start=1):
        if regex.search(line):
            excerpt = line.strip()
            if len(excerpt) > 240:
                excerpt = excerpt[:240] + "…"
            findings.append(Finding(rule=rule, path=str(path), line=i, excerpt=excerpt))
    return findings


def _extract_dockerfile_requirements(repo: Path, dockerfile: Path, docker_text: str) -> list[Path]:
    """
    Best-effort extraction of requirement file paths installed by Dockerfile.
    We look for:
      COPY <src> ...requirements*.txt
      RUN pip install ... -r <path>

    We intentionally keep this conservative: if we can't confidently link an
    installed requirements file, we fall back to checking for explicit
    `pip install gunicorn` in the Dockerfile itself.
    """
    rels: set[str] = set()
    for line in docker_text.splitlines():
        l = line.strip()
        if not l or l.startswith("#"):
            continue

        # COPY cloudrun_ingestor/requirements.txt ./cloudrun_ingestor/requirements.txt
        m = re.search(r"^\s*COPY\s+([^\s]+)\s+([^\s]+)\s*$", l, flags=re.IGNORECASE)
        if m:
            src = m.group(1).strip().strip('"').strip("'")
            if "requirements" in src and src.endswith(".txt"):
                rels.add(src)
            continue

        # RUN pip install ... -r cloudrun_ingestor/requirements.txt
        m2 = re.search(r"\s-r\s+([^\s]+requirements[^\s]*\.txt)\b", l)
        if m2:
            rels.add(m2.group(1).strip().strip('"').strip("'"))

    paths: list[Path] = []
    for r in sorted(rels):
        p = (repo / r).resolve()
        if p.exists() and p.is_file():
            paths.append(p)
    return paths


def _check_gunicorn_present_when_used(repo: Path, tracked: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    dockerfiles = [p for p in tracked if p.name == "Dockerfile" or p.name.startswith("Dockerfile")]
    for df in dockerfiles:
        if not _is_runtime_scope(df, repo):
            continue
        if not _is_text_candidate(df):
            continue
        txt = _read_text(df)
        df_lower = txt.lower()
        references_gunicorn = "gunicorn" in df_lower

        reqs = _extract_dockerfile_requirements(repo, df, txt)

        def _req_includes(pattern: str) -> bool:
            for rf in reqs:
                try:
                    rtxt = _read_text(rf)
                except Exception:
                    continue
                if re.search(pattern, rtxt):
                    return True
            return False

        # Detect Flask-based runtime services (heuristic, scoped per service Dockerfile).
        service_dir = df.parent
        service_rel = str(service_dir.relative_to(repo)).replace("\\", "/")

        flask_in_reqs = _req_includes(r"(?mi)^\s*flask(?:\[.*\])?\s*(==|>=|<=|~=|!=|$)")
        flask_in_code = False
        try:
            for p in tracked:
                if p.suffix.lower() != ".py":
                    continue
                try:
                    p.relative_to(service_dir)
                except Exception:
                    continue
                if not _is_runtime_scope(p, repo):
                    continue
                t = _read_text(p)
                if re.search(r"(?m)^\s*(from\s+flask\s+import\s+|import\s+flask\b)", t) or "Flask(" in t:
                    flask_in_code = True
                    break
        except Exception:
            flask_in_code = False

        uses_flask = bool(flask_in_reqs or flask_in_code)

        # If a runtime service uses Flask, require gunicorn (installed + used).
        if uses_flask:
            if not references_gunicorn:
                findings.append(
                    Finding(
                        rule="gunicorn_missing_from_runtime_service",
                        path=str(df),
                        line=1,
                        excerpt=f"{service_rel}: Flask detected but Dockerfile does not reference gunicorn.",
                    )
                )

        # If gunicorn is referenced OR Flask is detected, ensure gunicorn is installed.
        if not (references_gunicorn or uses_flask):
            continue

        pip_installs_gunicorn = bool(re.search(r"\bpip\s+install\b.*\bgunicorn\b", txt, flags=re.IGNORECASE))
        gunicorn_in_reqs = _req_includes(r"(?mi)^\s*gunicorn(?:\[.*\])?\s*(==|>=|<=|~=|!=|$)")

        if pip_installs_gunicorn or gunicorn_in_reqs:
            continue

        if not reqs:
            findings.append(
                Finding(
                    rule="gunicorn_missing_from_runtime_service",
                    path=str(df),
                    line=1,
                    excerpt="Dockerfile requires gunicorn but no requirements file detected and no `pip install gunicorn` found.",
                )
            )
        else:
            findings.append(
                Finding(
                    rule="gunicorn_missing_from_runtime_service",
                    path=str(df),
                    line=1,
                    excerpt=f"Dockerfile requires gunicorn but installed requirements do not include it (checked: {', '.join(str(p.relative_to(repo)) for p in reqs)}).",
                )
            )
    return findings


def main(argv: Sequence[str]) -> int:
    _ = argv
    repo = _repo_root()
    os.chdir(repo)

    tracked = _git_tracked_files(repo)

    findings: list[Finding] = []

    for p in tracked:
        if not _is_runtime_scope(p, repo):
            continue
        if not _is_text_candidate(p):
            continue
        try:
            txt = _read_text(p)
        except Exception:
            continue

        # sys.path mutation: enforce only on runtime python sources.
        if p.suffix.lower() == ".py":
            findings.extend(_find_regex("sys_path_mutation", p, txt, RE_SYS_PATH_MUTATION))

        # Flask dev server usage: runtime python + deploy scripts/docs in runtime scope.
        findings.extend(_find_regex("flask_dev_server_used", p, txt, RE_FLASK_DEV_SERVER))

        # python main.py usage: runtime command/config scope (Dockerfiles, shell, yaml).
        # Intentionally NOT scanning markdown/docs, to avoid failing on historical notes.
        if p.suffix.lower() in {".sh", ".yml", ".yaml"} or p.name.startswith("Dockerfile"):
            findings.extend(_find_regex("python_main_py_used", p, txt, RE_PYTHON_MAIN_DOT_PY))

    # gunicorn dependency presence when gunicorn is referenced in runtime Dockerfiles
    findings.extend(_check_gunicorn_present_when_used(repo, tracked))

    if not findings:
        print("OK: CI guardrail enforcement checks passed.")
        return 0

    print("ERROR: CI guardrail enforcement violations detected:\n", file=sys.stderr)
    for f in sorted(findings, key=lambda x: (x.rule, x.path, x.line))[:200]:
        rel = str(Path(f.path).resolve().relative_to(repo)).replace("\\", "/")
        print(f"- rule={f.rule} file={rel}:{f.line}\n  {f.excerpt}", file=sys.stderr)
    if len(findings) > 200:
        print(f"\n... and {len(findings) - 200} more", file=sys.stderr)

    print(
        "\nGuardrails enforced:\n"
        "- sys.path must not be mutated in runtime/service code\n"
        "- Flask dev server must not be used (no app.run / flask run)\n"
        "- Use python -m <module> or gunicorn; do not use python main.py in runtime configs\n"
        "- If gunicorn is used in a Dockerfile, it must be installed via requirements or pip\n",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

