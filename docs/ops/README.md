# Ops Docs (AgentTrader v2)

## Blueprint (auto-generated)

**Default post-lock operational mode**: `docs/ops/day1_ops.md` (Day 1 Ops Playbook).

## Index

- **Day 1 Ops Playbook (post-lock default mode)**: `docs/ops/day1_ops.md`
- **Agent mesh plan (single source of truth)**: `docs/ops/agent_mesh.md`
- **Reporting / readiness**: `docs/ops/reporting.md`
- **Runbooks**: `docs/ops/runbooks/`
- **Go/No-Go checklist (stub)**: `docs/ops/go_no_go.md`
- **Deploy guardrails (stub)**: `docs/ops/deploy_guardrails.md`
- **Disaster recovery plan (stub)**: `docs/ops/dr_plan.md`

This produces:
- `docs/BLUEPRINT.md`
- `audit_artifacts/blueprints/BLUEPRINT_<YYYYMMDD_HHMM>.md`

## Safety reminders

- Kill-switch defaults to **HALTED** in k8s: `k8s/05-kill-switch-configmap.yaml`
- Marketdata freshness must gate strategies/execution: `docs/MARKETDATA_HEALTH_CONTRACT.md`
- Execution remains **disabled** by default (do not enable in automation).

