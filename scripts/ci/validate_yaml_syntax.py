#!/usr/bin/env python3
"""
YAML syntax guard (SAFE / READ-ONLY).

Why this exists:
- YAML is easy to break with a single indent/quote mistake.
- This check fails fast and prints file:line:column with a clear reason.

Scope:
- Parses *tracked* *.yml/*.yaml files via `git ls-files`.
- Validates syntax only (not schemas).
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def _git_ls_files(patterns: list[str]) -> list[str]:
    cmd = ["git", "ls-files", *patterns]
    out = subprocess.check_output(cmd, text=True)
    return [line for line in out.splitlines() if line.strip()]


@dataclass(frozen=True)
class YamlError:
    path: str
    line: int | None
    column: int | None
    message: str


def _format_yaml_error(e: Exception) -> tuple[int | None, int | None, str]:
    # PyYAML exceptions typically include a `problem_mark` with line/column.
    mark = getattr(e, "problem_mark", None)
    if mark is not None:
        # Convert from 0-based to 1-based for humans.
        line = getattr(mark, "line", None)
        col = getattr(mark, "column", None)
        line = (line + 1) if isinstance(line, int) else None
        col = (col + 1) if isinstance(col, int) else None
    else:
        line = None
        col = None
    return line, col, f"{type(e).__name__}: {e}"


def main() -> int:
    try:
        import yaml  # type: ignore
    except Exception as e:  # noqa: BLE001
        print("ERROR: PyYAML is required for YAML syntax validation.", file=sys.stderr)
        print("Fix:", file=sys.stderr)
        print("  python3 -m pip install --upgrade pyyaml", file=sys.stderr)
        print(f"Details: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    files = _git_ls_files(["*.yml", "*.yaml"])
    if not files:
        print("OK: no tracked YAML files found.")
        return 0

    errors: list[YamlError] = []
    for f in files:
        p = Path(f)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            errors.append(YamlError(path=f, line=None, column=None, message=f"read failed: {e}"))
            continue

        try:
            # Parse all documents, purely for syntax validity.
            for _doc in yaml.safe_load_all(text):
                pass
        except Exception as e:  # noqa: BLE001
            line, col, msg = _format_yaml_error(e)
            errors.append(YamlError(path=f, line=line, column=col, message=msg))

    if errors:
        print("ERROR: YAML syntax validation failed.", file=sys.stderr)
        print(
            "Hint: Common causes are indentation mistakes, missing ':' after keys, or unclosed quotes.",
            file=sys.stderr,
        )
        for err in errors:
            loc = err.path
            if err.line is not None:
                loc += f":{err.line}"
                if err.column is not None:
                    loc += f":{err.column}"
            print(f"- {loc}: {err.message}", file=sys.stderr)
        return 1

    print(f"OK: parsed {len(files)} YAML files (syntax only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

