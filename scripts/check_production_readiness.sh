#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

ok() {
  echo "ok: $*"
}

require_cmd() {
  local cmd="$1"
  command -v "${cmd}" >/dev/null 2>&1 || fail "missing required command: ${cmd}"
}

banner() {
  echo
  echo "==> $*"
}

git_grep_no_matches() {
  local title="$1"
  local pattern="$2"
  shift 2

  banner "${title}"
  if git -C "${ROOT_DIR}" grep -n -I -E "${pattern}" -- "$@" >/dev/null 2>&1; then
    echo "Matched forbidden pattern: ${pattern}" >&2
    echo >&2
    git -C "${ROOT_DIR}" grep -n -I -E "${pattern}" -- "$@" >&2 || true
    fail "${title}"
  fi
  ok "${title}"
}

python_check() {
  local title="$1"
  shift 1
  banner "${title}"
  python3 - "$@" || fail "${title}"
  ok "${title}"
}

echo "Production-readiness enforcement (CI)"

require_cmd git
require_cmd python3

# ---- 1) sys.path usage (production code only; ban mutation hacks) ----
#
# Allow reading/logging sys.path; forbid runtime mutation in service code.
git_grep_no_matches \
  "ban sys.path mutation in production code" \
  '\bsys\.path\.(insert|append|extend)\s*\(|\bsys\.path\s*=' \
  backend cloudrun_ingestor cloudrun_consumer agenttrader mcp \
  ":(exclude)backend/**/tests/**" \
  ":(exclude)cloudrun_consumer/tests/**" \
  ":(exclude)backend/strategy_runner/examples/**"

# ---- 2) python main.py execution (ban for production entrypoints/config) ----
#
# We want explicit ASGI/WSGI servers (gunicorn/uvicorn) and module targets, not python main.py.
git_grep_no_matches \
  "ban python main.py execution in runtime configs" \
  '\bpython3?\b[[:space:]]+main\.py\b|\bpython3?\b[^[:cntrl:]]*?[[:space:]]+main\.py\b|CMD[[:space:]]*\[[^]]*\bpython3?\b[^]]*\bmain\.py\b' \
  .github infra k8s cloudrun_ingestor cloudrun_consumer backend ops scripts \
  ":(exclude)**/*.md" \
  ":(exclude)docs/**" \
  ":(exclude)audit_artifacts/**"

# ---- 3) gunicorn presence (Cloud Run ingestor) ----
python_check "require gunicorn in cloudrun_ingestor requirements" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

req = Path("cloudrun_ingestor/requirements.txt")
if not req.exists():
    print("missing file: cloudrun_ingestor/requirements.txt", file=sys.stderr)
    raise SystemExit(2)

txt = req.read_text(encoding="utf-8", errors="replace")
has = any(re.match(r"^\s*gunicorn(\b|[<=>])", line, flags=re.IGNORECASE) for line in txt.splitlines())
if not has:
    print("gunicorn is missing from cloudrun_ingestor/requirements.txt", file=sys.stderr)
    raise SystemExit(2)

print("found gunicorn in cloudrun_ingestor/requirements.txt")
PY

# ---- 4) risk guard symbols (import contract) ----
python_check "require risk guard symbols are present/importable" <<'PY'
from __future__ import annotations

import sys

try:
    from backend.vnext.risk_guard.interfaces import (  # noqa: F401
        RiskGuardLimits,
        RiskGuardState,
        RiskGuardTrade,
        evaluate_risk_guard,
    )
except Exception as e:  # noqa: BLE001
    print(f"failed to import risk guard symbols: {type(e).__name__}: {e}", file=sys.stderr)
    raise SystemExit(2)

missing = []
for name in ("RiskGuardLimits", "RiskGuardState", "RiskGuardTrade", "evaluate_risk_guard"):
    if name not in globals():
        missing.append(name)
if missing:
    print(f"missing risk guard symbols: {missing}", file=sys.stderr)
    raise SystemExit(2)

print("risk guard symbols present")
PY

echo
ok "production-readiness checks passed"

