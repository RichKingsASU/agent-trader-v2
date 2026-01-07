#!/usr/bin/env python3
"""
Lightweight dependency pinning enforcement for CI.

Policy:
- Requirements entries should be pinned with '==' (or be a direct reference using '@').
- We allow a small, repo-local allowlist for exceptions to keep CI deterministic while
  the repo transitions to fully pinned requirements.

This script is intentionally dependency-free (stdlib only).
"""

from __future__ import annotations

import glob
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path


ALLOWLIST_PATH = Path(".ci/requirements_allowlist.txt")


_SKIP_PREFIXES = (
    "#",
    "-r",
    "--requirement",
    "--index-url",
    "--extra-index-url",
    "--find-links",
    "--trusted-host",
    "-e",
    "--editable",
)


_PIN_OK_RE = re.compile(r"^(?P<req>[^;]+)(;.*)?$")
_HAS_STRICT_PIN_RE = re.compile(r"==|===")
_HAS_DIRECT_REF_RE = re.compile(r"\s@\s|@git\+|@https?://")
_HAS_RANGE_RE = re.compile(r"(>=|<=|~=|!=|>|<)")
_NAME_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    line: str
    reason: str


def _load_allowlist() -> tuple[set[str], set[str]]:
    """
    Returns:
      - exact_lines: full-line allowlist (stripped)
      - names: base package names (lowercased) allowlisted
    """
    exact_lines: set[str] = set()
    names: set[str] = set()

    if not ALLOWLIST_PATH.exists():
        return exact_lines, names

    for raw in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        exact_lines.add(s)
        m = _NAME_RE.match(s)
        if m:
            names.add(m.group(1).lower())

    return exact_lines, names


def _iter_requirement_files() -> list[Path]:
    # Keep it deterministic and small: only tracked-style requirement files.
    files = [Path(p) for p in glob.glob("**/requirements*.txt", recursive=True)]
    ignored_parts = {".venv", "venv", "__pycache__", "node_modules", ".git"}
    out: list[Path] = []
    for p in files:
        if any(part in ignored_parts for part in p.parts):
            continue
        if p.is_file():
            out.append(p)
    return sorted(out, key=lambda x: str(x))


def _base_name(line: str) -> str | None:
    # Strip markers/extras/version segments best-effort.
    s = line.strip()
    s = _PIN_OK_RE.sub(r"\g<req>", s).strip()
    if not s:
        return None
    if s.startswith(("git+", "http://", "https://")):
        return None
    m = _NAME_RE.match(s)
    if not m:
        return None
    name = m.group(1)
    return name.lower()


def _is_skippable(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return any(s.startswith(p) for p in _SKIP_PREFIXES)


def main() -> int:
    exact_allow, name_allow = _load_allowlist()
    req_files = _iter_requirement_files()
    findings: list[Finding] = []

    if not req_files:
        print("[ci_requirements] No requirements*.txt files found; skipping.")
        return 0

    for path in req_files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, raw in enumerate(lines, start=1):
            line = raw.strip()
            if _is_skippable(line):
                continue

            if line in exact_allow:
                continue

            base = _base_name(line)
            if base and base in name_allow:
                continue

            # Allow strict pins and direct refs.
            if _HAS_STRICT_PIN_RE.search(line) or _HAS_DIRECT_REF_RE.search(line):
                continue

            # Everything else is considered unpinned (ranges and bare names).
            if _HAS_RANGE_RE.search(line):
                reason = "unpinned version range (use '==', or allowlist intentionally)"
            else:
                reason = "unpinned package (use '==', or allowlist intentionally)"

            findings.append(
                Finding(
                    path=str(path),
                    line_no=idx,
                    line=line,
                    reason=reason,
                )
            )

    if findings:
        print("[ci_requirements] FAIL: Found unpinned requirements entries.")
        print(
            f"[ci_requirements] To temporarily allow exceptions, add package names or exact "
            f"lines to {ALLOWLIST_PATH}."
        )
        for f in findings:
            print(f"{f.path}:{f.line_no}: {f.reason}: {f.line}")
        return 1

    print(f"[ci_requirements] OK: All requirements entries are pinned (or allowlisted).")
    return 0


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent.parent)
    raise SystemExit(main())

