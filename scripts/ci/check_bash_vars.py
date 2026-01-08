#!/usr/bin/env python3
"""
Custom bash variable-usage guardrails (SAFE / READ-ONLY).

ShellCheck catches a lot, but we also block a few recurring "CI disaster" patterns
with very explicit messages:

1) GitHub Actions expressions inside bash scripts:
   - `${{ ... }}` only works in workflow YAML, not in `.sh` files.

2) Hyphens in variable names:
   - `FOO-BAR=...` is NOT a valid bash assignment.
   - `${FOO-BAR}` is almost certainly a bug (bash will interpret it oddly or fail).

3) `export $VAR=...`:
   - `export VAR=...` is valid; `export $VAR=...` is not.

This script prints file:line with the offending line to make fixes obvious.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _git_ls_files(pattern: str) -> list[str]:
    out = subprocess.check_output(["git", "ls-files", pattern], text=True)
    return [line for line in out.splitlines() if line.strip()]


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str
    snippet: str


RE_GHA_EXPR = re.compile(r"\$\{\{\s*[^}]+\s*\}\}")

# Likely-invalid variable expansion containing a hyphen:
#   ${FOO-BAR}
#
# NOTE: We DO NOT flag `$FOO-BAR` because it is frequently used intentionally as
# string concatenation (e.g., `$REGION-docker.pkg.dev/...`) and is not reliably
# distinguishable from a bug via regex alone.
RE_HYPHEN_EXPAND_BRACED = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*-[^}]+\}")

# Invalid export form (must be at start of line):
#   export $VAR=foo
RE_EXPORT_DOLLAR = re.compile(r"^\s*export\s+\$[A-Za-z_][A-Za-z0-9_]*=")


def main() -> int:
    sh_files = _git_ls_files("*.sh")
    if not sh_files:
        print("OK: no tracked *.sh files to scan.")
        return 0

    violations: list[Violation] = []

    for f in sh_files:
        p = Path(f)
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: failed to read {f}: {e}", file=sys.stderr)
            return 2

        for i, line in enumerate(lines, start=1):
            # Ignore full-line comments quickly; still scan inline comments because mistakes
            # often live in the code portion.
            if line.lstrip().startswith("#"):
                continue

            if RE_GHA_EXPR.search(line):
                violations.append(
                    Violation(
                        path=f,
                        line=i,
                        message="GitHub Actions expression `${{ ... }}` used inside a .sh file (won't be evaluated).",
                        snippet=line.strip(),
                    )
                )

            if RE_EXPORT_DOLLAR.search(line):
                violations.append(
                    Violation(
                        path=f,
                        line=i,
                        message="Invalid `export $VAR=...` usage. Use `export VAR=...` (no leading `$`).",
                        snippet=line.strip(),
                    )
                )

            # Braced hyphen expansions are almost always bugs.
            if RE_HYPHEN_EXPAND_BRACED.search(line):
                violations.append(
                    Violation(
                        path=f,
                        line=i,
                        message="Suspicious bash variable expansion containing '-'. Bash variable names cannot contain '-'.",
                        snippet=line.strip(),
                    )
                )

    if violations:
        print("ERROR: bash variable-usage guardrails failed.", file=sys.stderr)
        print("Fix the offending lines below. These are common CI/CD breakages.", file=sys.stderr)
        for v in violations:
            print(f"- {v.path}:{v.line}: {v.message}", file=sys.stderr)
            print(f"  > {v.snippet}", file=sys.stderr)
        return 1

    print(f"OK: scanned {len(sh_files)} bash scripts for variable-usage pitfalls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

