#!/usr/bin/env bash
set -euo pipefail

# Deterministic Cloud Build YAML validation (SAFE / READ-ONLY).
#
# Short report (why this exists):
# - What was broken: bash-local expansions inside `bash -c` blocks (e.g. `${IMAGE_REF}`, `${GIT_SHA}`,
#   `${COMMIT_SHA:-$SHORT_SHA}`) were interpreted by Cloud Build as substitutions and could hard-fail builds.
# - What changed: Cloud Build YAMLs now escape bash-local `$...` as `$$...` (so bash still sees `$...` at runtime),
#   and this validator prevents regressions.
#
# Validates:
# - YAML parses (Cloud Build configs only)
# - No forbidden ':latest' image tags (ignores Secret Manager `--update-secrets=...:latest`)
# - No forbidden 'AGENT_MODE=EXECUTE'
# - substitutions keys are valid Cloud Build user-defined keys (^_[A-Z0-9_]+$)
# - No unescaped bash-style $EXPANSIONS that Cloud Build would treat as substitutions
#
# Usage:
#   bash scripts/validate_cloudbuild_yaml.sh

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "${REPO_ROOT}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required." >&2
  exit 2
fi

python3 - <<'PY'
from __future__ import annotations

import glob
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception as e:  # noqa: BLE001
    print("ERROR: PyYAML is required to validate Cloud Build YAML.", file=sys.stderr)
    print("Fix (Cloud Shell):", file=sys.stderr)
    print("  python3 -m pip install --upgrade pyyaml", file=sys.stderr)
    print(f"Details: {type(e).__name__}: {e}", file=sys.stderr)
    raise SystemExit(2)


CLOUDBUILD_FILES = sorted(glob.glob("cloudbuild*.yaml") + glob.glob("infra/cloudbuild*.yaml"))
if not CLOUDBUILD_FILES:
    print("OK: no cloudbuild*.yaml files found.")
    raise SystemExit(0)


BUILTIN_SUBS = {
    # Common documented built-ins
    "PROJECT_ID",
    "BUILD_ID",
    "REPO_NAME",
    "BRANCH_NAME",
    "TAG_NAME",
    "REVISION_ID",
    "COMMIT_SHA",
    "SHORT_SHA",
    # Frequently used in triggers / newer APIs
    "TRIGGER_NAME",
    "LOCATION",
}

RE_USER_SUB_KEY = re.compile(r"^_[A-Z0-9_]+$")

# Detect any single-$ expansion-like token that can trip Cloud Build's substitution parsing.
# - Negative lookbehind prevents matching the 2nd '$' in '$$FOO' (escape form).
# - Captures:
#   1) ${...}  (braced)
#   2) $NAME   (simple)
#   3) $(      (command substitution)
#   4) $? $@ $# $* $! $1 ... (positional/special params)
RE_DOLLAR_TOKEN = re.compile(
    r"(?<!\$)\$("
    r"\{[^}]+\}"  # ${...}
    r"|[A-Za-z_][A-Za-z0-9_]*"  # $NAME
    r"|\("  # $(
    r"|[0-9]+"  # $1
    r"|[?@#*!]"  # $? $@ $# $* $!
    r")"
)


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    message: str
    snippet: str


def _line_of_offset(text: str, offset: int) -> int:
    # 1-based
    return text.count("\n", 0, offset) + 1


def _line_text(lines: list[str], line_no: int) -> str:
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].rstrip("\n")
    return ""


def _is_allowed_sub(name: str) -> bool:
    # Built-in substitutions: $PROJECT_ID, ${PROJECT_ID}, etc.
    if name in BUILTIN_SUBS:
        return True
    # User-defined substitutions: $_FOO / ${_FOO}
    if RE_USER_SUB_KEY.match(name):
        return True
    return False


def _scan_unescaped_dollars(path: str, text: str) -> list[Violation]:
    v: list[Violation] = []
    lines = text.splitlines()

    for m in RE_DOLLAR_TOKEN.finditer(text):
        token = m.group(0)  # includes leading '$'
        inner = m.group(1)
        line_no = _line_of_offset(text, m.start())
        snippet = _line_text(lines, line_no).strip()

        # Allow intended Cloud Build substitutions.
        if inner.startswith("{") and inner.endswith("}"):
            name = inner[1:-1].strip()
            # Only allow *pure* substitution names inside braces.
            # Anything else (e.g. ${FOO:-bar}) must be escaped for bash.
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) and _is_allowed_sub(name):
                continue
            v.append(
                Violation(
                    path=path,
                    line=line_no,
                    message=(
                        "Unescaped ${...} expression found. Cloud Build will parse this as a substitution and may fail. "
                        "If this is bash-local expansion, escape as $${...}."
                    ),
                    snippet=snippet,
                )
            )
            continue

        # $(...) command substitution should always be escaped as $$(
        if inner == "(":
            v.append(
                Violation(
                    path=path,
                    line=line_no,
                    message="Unescaped '$(' found. Escape bash command substitution as '$$(' to avoid Cloud Build parsing.",
                    snippet=snippet,
                )
            )
            continue

        # $NAME
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", inner):
            if _is_allowed_sub(inner):
                continue
            v.append(
                Violation(
                    path=path,
                    line=line_no,
                    message=(
                        f"Unescaped '${inner}' found (not a valid Cloud Build substitution). "
                        f"If this is a bash variable, escape as '$${inner}'."
                    ),
                    snippet=snippet,
                )
            )
            continue

        # Special/positional params ($1, $?, etc.) should be escaped as well.
        v.append(
            Violation(
                path=path,
                line=line_no,
                message=f"Unescaped '{token}' found. Escape bash expansions inside Cloud Build YAML as '$${token[1:]}'.",
                snippet=snippet,
            )
        )

    return v


def _parse_yaml_docs(path: str, text: str) -> list[object]:
    return list(yaml.safe_load_all(text))


def _validate_substitutions_keys(path: str, docs: list[object]) -> list[Violation]:
    v: list[Violation] = []
    raw_lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()

    for doc in docs:
        if not isinstance(doc, dict):
            continue
        subs = doc.get("substitutions")
        if subs is None:
            continue
        if not isinstance(subs, dict):
            v.append(
                Violation(
                    path=path,
                    line=1,
                    message="Top-level 'substitutions' must be a mapping/dict.",
                    snippet="substitutions: ...",
                )
            )
            continue

        for k in subs.keys():
            if not isinstance(k, str):
                v.append(
                    Violation(
                        path=path,
                        line=1,
                        message=f"substitutions key must be a string, got: {type(k).__name__}",
                        snippet=str(k),
                    )
                )
                continue
            if not RE_USER_SUB_KEY.match(k):
                v.append(
                    Violation(
                        path=path,
                        line=1,
                        message=f"Invalid substitutions key '{k}'. User-defined keys must match {RE_USER_SUB_KEY.pattern}.",
                        snippet=f"substitutions: {k}: ...",
                    )
                )

    return v


def _forbidden_latest(path: str, text: str) -> list[Violation]:
    v: list[Violation] = []
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        # Allow Secret Manager version selectors.
        if "--update-secrets=" in line and ":latest" in line:
            continue
        if ":latest" in line:
            v.append(
                Violation(
                    path=path,
                    line=i,
                    message="Forbidden ':latest' detected in Cloud Build config (pin to immutable tag/digest).",
                    snippet=line.strip(),
                )
            )
    return v


def _forbidden_agent_mode_execute(path: str, text: str) -> list[Violation]:
    v: list[Violation] = []
    lines = text.splitlines()
    for i, line in enumerate(lines, start=1):
        if "AGENT_MODE=EXECUTE" in line:
            v.append(
                Violation(
                    path=path,
                    line=i,
                    message="Forbidden 'AGENT_MODE=EXECUTE' detected in Cloud Build config.",
                    snippet=line.strip(),
                )
            )
    return v


violations: list[Violation] = []
parse_errors: list[Violation] = []

for f in CLOUDBUILD_FILES:
    p = Path(f)
    text = p.read_text(encoding="utf-8", errors="replace")

    # YAML parse first (fast fail).
    try:
        docs = _parse_yaml_docs(f, text)
    except Exception as e:  # noqa: BLE001
        # Best-effort line/col reporting from PyYAML.
        mark = getattr(e, "problem_mark", None)
        line = getattr(mark, "line", None)
        col = getattr(mark, "column", None)
        line_no = (line + 1) if isinstance(line, int) else 1
        msg = f"YAML parse error: {type(e).__name__}: {e}"
        parse_errors.append(Violation(path=f, line=line_no, message=msg, snippet=""))
        continue

    violations.extend(_validate_substitutions_keys(f, docs))
    violations.extend(_forbidden_latest(f, text))
    violations.extend(_forbidden_agent_mode_execute(f, text))
    violations.extend(_scan_unescaped_dollars(f, text))

if parse_errors:
    print("ERROR: Cloud Build YAML parse failures:", file=sys.stderr)
    for v in parse_errors:
        loc = f"{v.path}:{v.line}"
        print(f"- {loc}: {v.message}", file=sys.stderr)
    raise SystemExit(1)

if violations:
    print("ERROR: Cloud Build YAML validation failed.", file=sys.stderr)
    for v in sorted(violations, key=lambda x: (x.path, x.line, x.message)):
        loc = f"{v.path}:{v.line}"
        print(f"- {loc}: {v.message}", file=sys.stderr)
        if v.snippet:
            print(f"  > {v.snippet}", file=sys.stderr)
    raise SystemExit(1)

print(f"OK: validated {len(CLOUDBUILD_FILES)} Cloud Build YAML files.")
PY

