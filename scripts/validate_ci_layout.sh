#!/usr/bin/env bash
set -euo pipefail

# Validate CI layout / file references (lightweight, no dependencies beyond python3).
#
# Checks:
# - CI safety guard script exists (+ executable)
# - Required CI helper scripts exist
# - cloudbuild.yaml references only valid paths (scripts + Dockerfiles)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CB_YAML="${ROOT_DIR}/cloudbuild.yaml"

fail() {
  echo "ERROR: $*" >&2
  return 1
}

require_file() {
  local rel="$1"
  local path="${ROOT_DIR}/${rel}"
  if [[ ! -f "${path}" ]]; then
    fail "missing required file: ${rel}"
  fi
}

require_executable() {
  local rel="$1"
  local path="${ROOT_DIR}/${rel}"
  if [[ ! -f "${path}" ]]; then
    fail "missing required file: ${rel}"
  fi
  if [[ ! -x "${path}" ]]; then
    fail "file is not executable: ${rel}"
  fi
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    fail "missing required command: ${cmd}"
  fi
}

echo "== ci-validate =="

# 1) Safety guard exists (and is executable because Makefile uses it directly)
require_executable "scripts/ci_safety_guard.sh"

# 2) Required scripts exist
require_file "scripts/ci_import_gate.sh"

# 3) cloudbuild.yaml references valid paths
require_file "cloudbuild.yaml"
require_cmd python3

python3 - "${ROOT_DIR}" "${CB_YAML}" <<'PY'
import os
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
cloudbuild = Path(sys.argv[2])

txt = cloudbuild.read_text(encoding="utf-8")

errors: list[str] = []

def require_exists(rel: str, kind: str) -> None:
    # Rel is expected to be a repo-relative POSIX-ish path.
    if rel.startswith("./"):
        rel = rel[2:]
    if rel.startswith("/"):
        errors.append(f"{kind} reference is absolute (expected repo-relative): {rel}")
        return
    if ".." in rel.split("/"):
        errors.append(f"{kind} reference contains '..' (not allowed): {rel}")
        return
    p = root / rel
    if not p.exists():
        errors.append(f"missing {kind} referenced by cloudbuild.yaml: {rel}")


# Extract script references like: sh ./scripts/foo.sh, bash ./scripts/foo.sh, ./scripts/foo.sh
script_refs = set(
    m.group(1)
    for m in re.finditer(r"(?<![\w./-])\./(scripts/[A-Za-z0-9_./-]+\.(?:sh|py))\b", txt)
)

for rel in sorted(script_refs):
    require_exists(rel, "script")


# Extract Dockerfile references used with -f.
dockerfile_refs: set[str] = set()

# a) Shell form: docker build -f path/to/Dockerfile ...
for m in re.finditer(r"(?:^|\s)-f\s+([^\s'\"\\]+)", txt, flags=re.MULTILINE):
    dockerfile_refs.add(m.group(1))

# b) YAML args list form: '-f', 'path/to/Dockerfile'
for m in re.finditer(r"['\"]-f['\"]\s*,\s*['\"]([^'\"]+)['\"]", txt):
    dockerfile_refs.add(m.group(1))

for rel in sorted(dockerfile_refs):
    # Filter obvious non-paths / variable substitutions
    if any(ch in rel for ch in ("$", "{", "}", "\n")):
        continue
    require_exists(rel, "Dockerfile")


# Safety guard step presence (either explicit script usage or named step)
if ("ci_safety_guard.sh" not in txt) and ("Safety Guard" not in txt):
    errors.append("cloudbuild.yaml does not appear to include a safety guard step")


if errors:
    print("CI layout validation FAILED:", file=sys.stderr)
    for e in errors:
        print(f" - {e}", file=sys.stderr)
    raise SystemExit(2)

print("OK: CI layout validation passed.")
print(f"OK: referenced scripts: {len(script_refs)}")
print(f"OK: referenced Dockerfiles: {len(dockerfile_refs)}")
PY
