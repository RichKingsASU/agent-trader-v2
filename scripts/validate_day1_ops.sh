#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 - Day 1 Ops Validator (read-only)
#
# Verifies the "Day 1 Ops" artifacts exist and that the repo does not contain
# active (non-suspended) cron/scheduler scaffolding.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail=0
reasons=()

add_fail() { fail=1; reasons+=("$*"); }
check_file() {
  local rel="$1"
  if [[ ! -f "${ROOT_DIR}/${rel}" ]]; then
    add_fail "missing required file: ${rel}"
  fi
}

check_exec() {
  local rel="$1"
  if [[ ! -f "${ROOT_DIR}/${rel}" ]]; then
    add_fail "missing required script: ${rel}"
    return
  fi
  if [[ ! -x "${ROOT_DIR}/${rel}" ]]; then
    add_fail "script is not executable: ${rel}"
  fi
}

check_file "docs/ops/day1_ops.md"
check_file "docs/ops/README.md"

check_exec "scripts/validate_day1_ops.sh"
check_exec "scripts/readiness_check.sh"
check_exec "scripts/capture_config_snapshot.sh"
check_exec "scripts/postmortem_replay.sh"
check_exec "scripts/generate_blueprint.sh"
check_exec "scripts/report_v2_deploy.sh"

# Ensure referenced supporting docs exist (non-fatal, but expected)
check_file "docs/KILL_SWITCH.md"
check_file "docs/MARKETDATA_HEALTH_CONTRACT.md"
check_file "docs/ops/reporting.md"

# Cron/scheduler scaffolds must be suspended (commented) or absent.
scan_active_lines() {
  local pattern="$1"
  shift
  local paths=("$@")

  local matches=""
  if command -v rg >/dev/null 2>&1; then
    matches="$(rg -n --no-heading "${pattern}" "${paths[@]}" 2>/dev/null || true)"
  else
    # grep fallback
    matches="$(grep -R -n -E "${pattern}" "${paths[@]}" 2>/dev/null || true)"
  fi

  [[ -z "${matches}" ]] && return 0

  local active=0
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    # format: file:line:content
    local content="${line#*:}"
    content="${content#*:}"
    if [[ ! "${content}" =~ ^[[:space:]]*# ]]; then
      active=1
    fi
  done <<< "${matches}"

  if [[ "${active}" -eq 1 ]]; then
    add_fail "found active (non-commented) scheduler/cron scaffold matching /${pattern}/"
  fi
}

# Flag explicit scheduler creation commands if not commented
scan_active_lines "gcloud[[:space:]]+scheduler[[:space:]]+jobs[[:space:]]+create" "${ROOT_DIR}/scripts" "${ROOT_DIR}/infra" || true
scan_active_lines "crontab[[:space:]]+-" "${ROOT_DIR}/scripts" "${ROOT_DIR}/infra" || true

# GitHub Actions scheduled workflows should not exist in post-lock default mode.
if command -v rg >/dev/null 2>&1; then
  if rg -n --no-heading '^[[:space:]]*schedule:' "${ROOT_DIR}/.github/workflows" >/dev/null 2>&1; then
    add_fail "found GitHub Actions schedule trigger under .github/workflows (must be removed/suspended)"
  fi
else
  if grep -R -n -E '^[[:space:]]*schedule:' "${ROOT_DIR}/.github/workflows" >/dev/null 2>&1; then
    add_fail "found GitHub Actions schedule trigger under .github/workflows (must be removed/suspended)"
  fi
fi

if [[ "${fail}" -eq 0 ]]; then
  echo "PASS: Day 1 Ops validation OK"
  exit 0
fi

echo "FAIL: Day 1 Ops validation failed"
for r in "${reasons[@]}"; do
  echo "- ${r}"
done
exit 1

