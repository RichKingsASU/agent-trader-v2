#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

# Script inventory/risk policy must run first (fast fail).
PY_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  echo "ERROR: python is required to run scripts/ci/enforce_script_risk_policy.py" >&2
  exit 2
fi
"${PY_BIN}" "${REPO_ROOT}/scripts/ci/enforce_script_risk_policy.py"

mapfile -t YAML_FILES < <(git ls-files '*.yaml' '*.yml')

if [[ ${#YAML_FILES[@]} -eq 0 ]]; then
  echo "No YAML files found (git ls-files)."
  exit 0
fi

YAMLLINT_CMD=()
if command -v yamllint >/dev/null 2>&1; then
  YAMLLINT_CMD=(yamllint)
elif python3 -c "import yamllint" >/dev/null 2>&1; then
  YAMLLINT_CMD=(python3 -m yamllint)
fi

if [[ ${#YAMLLINT_CMD[@]} -gt 0 ]]; then
  # Keep this lightweight: enforce parse + 2-space indentation + no duplicate keys.
  # Avoid noisy style rules that vary by repo (line length, blank lines, etc.).
  "${YAMLLINT_CMD[@]}" -f parsable -d "{extends: default, rules: {indentation: {spaces: 2, indent-sequences: consistent}, key-duplicates: enable, line-length: disable, document-start: disable, truthy: disable, empty-lines: disable, comments: disable, comments-indentation: disable, commas: disable}}" "${YAML_FILES[@]}"
  exit 0
fi

python3 - <<'PY'
import sys
from pathlib import Path

try:
    import yaml  # PyYAML
except Exception as e:
    print("ERROR: neither yamllint nor PyYAML is available.", file=sys.stderr)
    print("Install one of:", file=sys.stderr)
    print("  - yamllint (preferred): python3 -m pip install --upgrade yamllint", file=sys.stderr)
    print("  - pyyaml: python3 -m pip install --upgrade pyyaml", file=sys.stderr)
    print(f"Details: {e}", file=sys.stderr)
    sys.exit(2)

from subprocess import check_output

files = check_output(["git", "ls-files", "*.yaml", "*.yml"], text=True).splitlines()
bad = []
for f in files:
    p = Path(f)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue
    try:
        list(yaml.safe_load_all(text))
    except Exception as e:
        bad.append((f, str(e)))

if bad:
    print("YAML parse failures:", file=sys.stderr)
    for f, err in bad:
        print(f"- {f}", file=sys.stderr)
        print(f"  {err}", file=sys.stderr)
    sys.exit(1)

print(f"OK: parsed {len(files)} YAML files")
PY
