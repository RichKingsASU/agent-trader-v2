#!/usr/bin/env bash
set -euo pipefail

# AgentTrader v2 - Blueprint Generator (read-only)
#
# Produces a deterministic markdown snapshot of "what exists" for audits/onboarding.
# MUST NOT modify production state.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./scripts/generate_blueprint.sh [--output-dir <dir>]
EOF
}

OUT_DIR=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir)
      OUT_DIR="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

NOW_UTC="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
STAMP="$(date -u +'%Y%m%dT%H%M%SZ')"
GIT_SHA="$(git -C "${ROOT_DIR}" rev-parse HEAD 2>/dev/null || echo "UNKNOWN")"
GIT_BRANCH="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "UNKNOWN")"

if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="${ROOT_DIR}/audit_artifacts/blueprint/${STAMP}"
fi
mkdir -p "${OUT_DIR}"

OUT_MD="${OUT_DIR}/blueprint.md"

{
  echo "# AgentTrader v2 — Blueprint Snapshot"
  echo
  echo "- Generated (UTC): \`${NOW_UTC}\`"
  echo "- Git SHA: \`${GIT_SHA}\`"
  echo "- Git branch: \`${GIT_BRANCH}\`"
  echo
  echo "## Always-on components (Day 1 Ops)"
  echo
  echo "- \`marketdata-mcp-server\`"
  echo "  - K8s: \`k8s/20-marketdata-mcp-server-deployment-and-service.yaml\`"
  echo "  - Health: \`GET /healthz\` (see \`docs/MARKETDATA_HEALTH_CONTRACT.md\`)"
  echo "- \`strategy-engine\` (strategy runtimes)"
  echo "  - K8s: \`k8s/10-gamma-strategy-statefulset.yaml\`, \`k8s/11-whale-strategy-statefulset.yaml\`"
  echo "  - Safety: kill switch mount \`k8s/05-kill-switch-configmap.yaml\`"
  echo "- \`mission-control\` (frontend page)"
  echo "  - UI route: \`frontend/src/pages/MissionControl.tsx\`"
  echo "- \`ops-ui\` (frontend ops pages)"
  echo "  - UI routes: \`frontend/src/pages/ops/*\`"
  echo
  echo "## Operational safety invariants"
  echo
  echo "- Kill switch doc: \`docs/KILL_SWITCH.md\`"
  echo "- Marketdata heartbeat doc: \`docs/MARKETDATA_HEALTH_CONTRACT.md\`"
  echo "- Deploy guardrails (refuse EXECUTE): \`docs/ops/deploy_guardrails.md\`"
  echo
  echo "## K8s manifests (repo snapshot)"
  echo
  if [[ -d "${ROOT_DIR}/k8s" ]]; then
    echo '```text'
    (cd "${ROOT_DIR}" && ls -1 k8s | sed 's/^/k8s\//') || true
    echo '```'
  else
    echo "_No k8s/ directory found in this checkout._"
  fi
  echo
  echo "## Read-only ops commands"
  echo
  echo "- Readiness check: \`./scripts/readiness_check.sh\`"
  echo "- Deploy report: \`./scripts/report_v2_deploy.sh --skip-health\`"
  echo "- Config snapshot: \`./scripts/capture_config_snapshot.sh\`"
  echo "- Replay timeline: \`./scripts/postmortem_replay.sh <logs>\`"
  echo
  echo "## Notes"
  echo
  echo "- This blueprint is read-only evidence. It does not deploy or modify production."
  echo "- Day 1 Ops Playbook: \`docs/ops/day1_ops.md\`"
} > "${OUT_MD}"

echo "OK: wrote ${OUT_MD}"

