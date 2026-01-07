# AgentTrader v2 — Ops Documentation Index

This directory contains **institutional operations governance** for AgentTrader v2 (safety-first; execution disabled unless explicitly authorized).

## Core “Go/No-Go” package

- **Production Readiness Checklist (single source)**: [`go_no_go.md`](./go_no_go.md)
- **Pre-Market Runbook**: [`runbooks/pre_market.md`](./runbooks/pre_market.md)
- **Post-Market Runbook**: [`runbooks/post_market.md`](./runbooks/post_market.md)
- **Deployment reporting (auditable snapshots)**: [`reporting.md`](./reporting.md)

## Automation

- **Deterministic readiness gate**: `scripts/readiness_check.sh`
  - Writes: `audit_artifacts/readiness_report.md` and `audit_artifacts/readiness_report.json`
- **Deployed-state report**: `scripts/report_v2_deploy.sh`
  - Writes: `audit_artifacts/deploy_report.md` and `audit_artifacts/deploy_report.json`

## Related references (repo-wide)

- **Kill switch operations**: `docs/KILL_SWITCH.md`
- **GCP deployment guide**: `docs/DEPLOY_GCP.md`
- **Deploy script (includes guardrails)**: `scripts/deploy_v2.sh`

## Optional docs (link here if/when added)

- `deploy_guardrails.md` (not currently present)
- `disaster_recovery.md` (not currently present)

