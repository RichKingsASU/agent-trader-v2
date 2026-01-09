#!/usr/bin/env python3
"""
Python/runtime guardrails (SAFE / READ-ONLY).

These guardrails are intended to prevent a few high-impact production footguns:

- sys.path mutation (fragile imports; environment-dependent behavior)
- "python main.py" execution (often implies Flask dev server usage in prod)
- Flask dev server usage / warnings patterns (non-production server)
- missing gunicorn when Flask is present in service requirements

Important design choice:
- This check is DIFF-BASED for most rules (it inspects newly-added lines only).
  The repo already contains some legacy patterns (e.g., tests/scripts), and the
  goal of this guard is to prevent *new* occurrences from being introduced.

This script prints clear, actionable file:line violations and exits non-zero on
failure. It never modifies the repository.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _git_ok(*args: str) -> bool:
    try:
        subprocess.check_call(
            ["git", *args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _ensure_ref(ref: str) -> None:
    if _git_ok("rev-parse", "--verify", ref):
        return
    # Best-effort fetch (actions/checkout fetch-depth may be limited).
    remote, _, name = ref.partition("/")
    if remote and name:
        subprocess.check_call(["git", "fetch", "--no-tags", remote, name])


def _diff_range() -> str | None:
    """
    Return a git diff range string suitable for `git diff <range>`, or None if
    we can't determine a meaningful range (e.g., initial commit).
    """
    base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base_ref:
        ref = f"origin/{base_ref}"
        _ensure_ref(ref)
        return f"{ref}...HEAD"

    # Non-PR context (push / workflow_dispatch):
    # - on main: compare against previous commit (enforce on every change to main)
    # - on non-main branches: compare against origin/main (so manual runs don't
    #   accidentally trip on unrelated historical commits in the branch).
    ref_name = os.environ.get("GITHUB_REF_NAME", "").strip()
    if not ref_name:
        try:
            ref_name = _git("rev-parse", "--abbrev-ref", "HEAD").strip()
        except Exception:
            ref_name = ""

    if ref_name and ref_name != "main":
        try:
            _ensure_ref("origin/main")
            return "origin/main...HEAD"
        except Exception:
            # Fall back to previous commit if origin/main isn't available.
            pass

    try:
        _git("rev-parse", "HEAD~1")
        return "HEAD~1..HEAD"
    except Exception:
        return None


@dataclass(frozen=True)
class AddedLine:
    path: str
    line: int
    text: str


def _iter_added_lines(diff_range: str) -> list[AddedLine]:
    """
    Parse `git diff` output and yield added lines with (best-effort) new-file line numbers.
    """
    cmd = [
        "git",
        "diff",
        "--no-color",
        "--unified=0",
        "--diff-filter=AM",
        diff_range,
    ]
    out = subprocess.check_output(cmd, text=True, errors="replace")

    current_file: str | None = None
    new_line_no: int | None = None
    added: list[AddedLine] = []

    hunk_re = re.compile(r"^\@\@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? \@\@")

    for raw in out.splitlines():
        if raw.startswith("+++ "):
            # Example: "+++ b/path/to/file.py"
            # Ignore deletions (+++ /dev/null).
            if raw.strip() == "+++ /dev/null":
                current_file = None
                continue
            if raw.startswith("+++ b/"):
                current_file = raw[len("+++ b/") :].strip()
            else:
                current_file = raw[len("+++ ") :].strip()
            continue

        m = hunk_re.match(raw)
        if m:
            new_line_no = int(m.group(1))
            continue

        if current_file is None or new_line_no is None:
            continue

        # Skip file headers
        if raw.startswith("diff --git ") or raw.startswith("--- "):
            continue

        # Context lines (should be none with unified=0, but keep logic safe)
        if raw.startswith(" "):
            new_line_no += 1
            continue

        # Removed lines don't advance new file line counter.
        if raw.startswith("-"):
            continue

        # Added line
        if raw.startswith("+") and not raw.startswith("+++"):
            added.append(AddedLine(path=current_file, line=new_line_no, text=raw[1:]))
            new_line_no += 1
            continue

    return added


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str
    snippet: str


RE_SYS_PATH_MUTATION = re.compile(r"\bsys\.path\.(append|insert|extend)\s*\(")
RE_SYS_PATH_PLUS_EQ = re.compile(r"\bsys\.path\s*\+\=")
RE_SYS_PATH_ASSIGN = re.compile(r"\bsys\.path\s*=")

# Matches python invocation with optional flags, e.g.:
# - python main.py
# - python3 -u main.py
RE_PYTHON_MAIN = re.compile(r"\bpython(?:3)?\s+(?:-[^\s]+\s+)*main\.py\b")

RE_FLASK_RUN = re.compile(r"\bflask\s+run\b", re.IGNORECASE)
RE_APP_RUN = re.compile(r"\bapp\.run\s*\(")
RE_WERKZEUG_RUN_SIMPLE = re.compile(r"\bwerkzeug\.serving\.run_simple\s*\(")
RE_FLASK_DEV_WARNING = re.compile(r"WARNING:\s+This is a development server", re.IGNORECASE)


def _is_markdown(path: str) -> bool:
    return Path(path).suffix.lower() == ".md"


def _is_dockerfile(path: str) -> bool:
    return Path(path).name.startswith("Dockerfile")


def _should_scan_for_python_main(path: str) -> bool:
    """
    We intentionally skip Markdown/docs to avoid blocking explanatory text.
    """
    if _is_markdown(path):
        return False
    p = Path(path)
    return _is_dockerfile(path) or p.suffix.lower() in {".sh", ".yml", ".yaml"}


def _should_scan_for_flask_dev_strings(path: str) -> bool:
    """
    Skip Markdown/docs; keep this focused on runnable configs and code.
    """
    if _is_markdown(path):
        return False
    p = Path(path)
    return _is_dockerfile(path) or p.suffix.lower() in {".py", ".sh", ".yml", ".yaml", ".txt"}


def _parse_requirements_packages(text: str) -> set[str]:
    """
    Extract normalized package names from a requirements file.

    Notes:
    - ignores comments and -r includes
    - normalizes package names to lowercase
    - accepts `pkg`, `pkg==x`, `pkg>=x`, `pkg[extra]==x`
    """
    pkgs: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            continue
        # Strip environment markers (rare here, but safe).
        line = line.split(";", 1)[0].strip()
        # Keep only the left-most specifier/URL.
        # e.g. gunicorn==22.0.0 -> gunicorn
        # e.g. Flask>=3 -> flask
        # e.g. something[extra]==1 -> something
        m = re.match(r"^([A-Za-z0-9_.-]+)", line)
        if not m:
            continue
        name = m.group(1).split("[", 1)[0].lower()
        pkgs.add(name)
    return pkgs


def _check_gunicorn_presence() -> list[str]:
    """
    Enforce: if Flask is listed in a service requirements file, gunicorn must be present too.
    """
    tracked = _git("ls-files").splitlines()
    req_files = [
        f
        for f in tracked
        if (f.endswith(".txt") and Path(f).name.startswith("requirements"))
    ]

    failures: list[str] = []
    for f in req_files:
        # Skip docs/audits.
        if f.startswith("docs/") or f.startswith("audit_artifacts/"):
            continue
        p = Path(f)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            failures.append(f"- {f}: failed to read requirements file: {e}")
            continue

        pkgs = _parse_requirements_packages(text)
        if "flask" in pkgs and "gunicorn" not in pkgs:
            failures.append(
                f"- {f}: lists Flask but is missing gunicorn (production WSGI server)."
            )

    return failures


def main() -> int:
    diff_range = _diff_range()
    if diff_range is None:
        print("OK: no diff range available; skipping diff-based runtime guardrails.")
        diff_lines: list[AddedLine] = []
    else:
        diff_lines = _iter_added_lines(diff_range)

    violations: list[Violation] = []

    for al in diff_lines:
        path = al.path
        line = al.line
        text = al.text

        # 1) sys.path mutation (Python only)
        if path.endswith(".py"):
            if RE_SYS_PATH_MUTATION.search(text) or RE_SYS_PATH_PLUS_EQ.search(text) or RE_SYS_PATH_ASSIGN.search(text):
                violations.append(
                    Violation(
                        path=path,
                        line=line,
                        message="Forbidden: sys.path mutation (fragile, environment-dependent imports).",
                        snippet=text.rstrip(),
                    )
                )

        # 2) "python main.py" usage (runnable configs only; ignore docs)
        if _should_scan_for_python_main(path) and RE_PYTHON_MAIN.search(text):
            violations.append(
                Violation(
                    path=path,
                    line=line,
                    message='Forbidden: "python main.py" usage (use a production server / module entrypoint).',
                    snippet=text.rstrip(),
                )
            )

        # 3) Flask dev server warnings / usage patterns
        if _should_scan_for_flask_dev_strings(path):
            if (
                RE_FLASK_RUN.search(text)
                or RE_APP_RUN.search(text)
                or RE_WERKZEUG_RUN_SIMPLE.search(text)
                or RE_FLASK_DEV_WARNING.search(text)
            ):
                violations.append(
                    Violation(
                        path=path,
                        line=line,
                        message="Forbidden: Flask dev-server usage/warning pattern detected (non-production server).",
                        snippet=text.rstrip(),
                    )
                )

    # 4) missing gunicorn (repo-wide requirements consistency)
    gunicorn_failures = _check_gunicorn_presence()

    if violations or gunicorn_failures:
        print("ERROR: runtime guardrails failed.", file=sys.stderr)

        if violations:
            print("", file=sys.stderr)
            print("Newly-introduced violations (added lines):", file=sys.stderr)
            for v in violations:
                print(f"- {v.path}:{v.line}: {v.message}", file=sys.stderr)
                print(f"  > {v.snippet}", file=sys.stderr)

        if gunicorn_failures:
            print("", file=sys.stderr)
            print("Gunicorn requirements violations:", file=sys.stderr)
            for msg in gunicorn_failures:
                print(msg, file=sys.stderr)

        return 1

    print("OK: runtime guardrails passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

