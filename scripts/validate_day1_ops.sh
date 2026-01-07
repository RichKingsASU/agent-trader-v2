#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 — Day 1 Ops validator (read-only)
#
# Validates that the Day 1 Ops operating model is present and internally consistent:
# - docs/ops/day1_ops.md exists
# - referenced scripts exist
# - k8s cron scaffolds (if present) are suspended and do not contain mutating kubectl verbs
#
# Output: prints PASS/FAIL with reasons. Exits non-zero on FAIL.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

FAILURES=()
WARNINGS=()

fail() { FAILURES+=("$1"); }
warn() { WARNINGS+=("$1"); }

check_file_exists() {
  local rel="$1"
  if [[ ! -f "${ROOT_DIR}/${rel}" ]]; then
    fail "missing required file: ${rel}"
  fi
}

echo "Validating AgentTrader v2 Day 1 Ops (read-only)..."

# 1) Playbook exists
check_file_exists "docs/ops/day1_ops.md"

# 2) Referenced scripts exist (as defined in the playbook)
check_file_exists "scripts/readiness_check.sh"
check_file_exists "scripts/ops_pre_market.sh"
check_file_exists "scripts/ops_post_market.sh"
check_file_exists "scripts/report_v2_deploy.sh"
check_file_exists "scripts/capture_lkg.sh"
check_file_exists "scripts/replay_from_logs.py"
check_file_exists "scripts/capture_config_snapshot.sh"
check_file_exists "scripts/blueprint_generator.sh"

# 3) Cron scaffolds suspended or read-only (repo manifests)
CRON_DIR="${ROOT_DIR}/k8s/ops/cronjobs"
if [[ -d "${CRON_DIR}" ]]; then
  shopt -s nullglob
  cron_files=("${CRON_DIR}"/*.yaml)
  shopt -u nullglob

  if [[ ${#cron_files[@]} -eq 0 ]]; then
    warn "no cron scaffold YAMLs found under k8s/ops/cronjobs/"
  else
    for f in "${cron_files[@]}"; do
      if ! python3 - "${f}" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()

is_cronjob = any(re.match(r"^\s*kind:\s*CronJob\s*$", ln) for ln in lines)
if not is_cronjob:
    # Not a CronJob manifest; ignore.
    raise SystemExit(0)

fname = path.name
disabled_by_name = ".disabled" in fname

def _is_comment(ln: str) -> bool:
    return bool(re.match(r"^\s*#", ln))

non_comment = [ln for ln in lines if not _is_comment(ln)]

has_suspend_true = any(re.match(r"^\s*suspend:\s*true\s*$", ln, re.IGNORECASE) for ln in non_comment)
has_suspend_false = any(re.match(r"^\s*suspend:\s*false\s*$", ln, re.IGNORECASE) for ln in non_comment)

# Mutating kubectl verbs are forbidden in post-lock scaffolds.
mutating = re.compile(r"\bkubectl\s+(apply|patch|delete|scale|rollout|replace|edit|label|annotate)\b", re.IGNORECASE)
mut_hits = [ln.strip() for ln in non_comment if mutating.search(ln)]

# Flag images that use :latest (allowed only if suspended; warn elsewhere).
latest_img = re.compile(r"^\s*image:\s*.*:latest\b", re.IGNORECASE)
latest_hits = [ln.strip() for ln in non_comment if latest_img.search(ln)]

errors = []
warnings = []

if mut_hits:
    errors.append("mutating kubectl verb(s) present: " + "; ".join(mut_hits[:3]) + (" ..." if len(mut_hits) > 3 else ""))

if has_suspend_false and not disabled_by_name:
    errors.append("CronJob is not suspended (suspend: false)")
elif (not has_suspend_true) and (not disabled_by_name):
    # If suspend is omitted, treat as unsafe under production lock.
    errors.append("CronJob missing explicit 'suspend: true' (required under production lock)")

if latest_hits and (not disabled_by_name) and (not has_suspend_true):
    warnings.append("uses :latest image tag without being suspended")

if errors:
    print("ERROR\t" + str(path) + "\t" + " | ".join(errors))
    raise SystemExit(2)

if warnings:
    print("WARN\t" + str(path) + "\t" + " | ".join(warnings))
raise SystemExit(0)
PY
      then
        # Python printed an ERROR line; record file path in failures.
        fail "cron scaffold unsafe: $(basename "${f}") (must be suspended and non-mutating)"
      else
        # Capture any WARN lines for visibility.
        warn_line="$(python3 - "${f}" <<'PY' || true
import re,sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8", errors="replace")
lines = [ln for ln in text.splitlines() if not re.match(r"^\s*#", ln)]
if not any(re.match(r"^\s*kind:\s*CronJob\s*$", ln) for ln in lines):
    raise SystemExit(0)
latest = [ln.strip() for ln in lines if re.match(r"^\s*image:\s*.*:latest\b", ln, re.IGNORECASE)]
suspend_true = any(re.match(r"^\s*suspend:\s*true\s*$", ln, re.IGNORECASE) for ln in lines)
disabled = ".disabled" in path.name
if latest and (suspend_true or disabled):
    print(f"{path.name}: uses :latest image tag but is suspended (ok as scaffold)")
PY
)"
        if [[ -n "${warn_line}" ]]; then
          warn "${warn_line}"
        fi
      fi
    done
  fi
else
  warn "k8s/ops/cronjobs directory not found; skipping cron scaffold checks"
fi

# 4) Final result
if [[ ${#FAILURES[@]} -eq 0 ]]; then
  echo "PASS: Day 1 Ops playbook + guardrails validated."
  if [[ ${#WARNINGS[@]} -gt 0 ]]; then
    echo
    echo "Warnings:"
    for w in "${WARNINGS[@]}"; do
      echo " - ${w}"
    done
  fi
  exit 0
fi

echo "FAIL: Day 1 Ops validation failed."
echo
echo "Reasons:"
for f in "${FAILURES[@]}"; do
  echo " - ${f}"
done
if [[ ${#WARNINGS[@]} -gt 0 ]]; then
  echo
  echo "Warnings:"
  for w in "${WARNINGS[@]}"; do
    echo " - ${w}"
  done
fi
exit 1

