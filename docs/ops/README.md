# Ops Docs (AgentTrader v2)

## Blueprint (auto-generated)

- **Blueprint**: `docs/BLUEPRINT.md`
- **Regenerate**:

- **Agent mesh plan (single source of truth)**: `docs/ops/agent_mesh.md`
- **Reporting / readiness**: `docs/ops/reporting.md`
- **Production lock (v2 freeze)**: `ops/PRODUCTION_LOCK.md`
- **Validation scripts**:
  - `scripts/validate_production_lock.sh`
  - `scripts/tag_production_lock.sh`
- **Runbooks**: `docs/ops/runbooks/`
- **Go/No-Go checklist (stub)**: `docs/ops/go_no_go.md`
- **Deploy guardrails (stub)**: `docs/ops/deploy_guardrails.md`
- **Disaster recovery plan (stub)**: `docs/ops/dr_plan.md`
 
## Controlled unlocks (human-gated)

All changes to locked scope must follow the controlled unlock procedure in `ops/PRODUCTION_LOCK.md`.

This produces:
- `docs/BLUEPRINT.md`
- `audit_artifacts/blueprints/BLUEPRINT_<YYYYMMDD_HHMM>.md`

## Safety reminders

- Kill-switch defaults to **HALTED** in k8s: `k8s/05-kill-switch-configmap.yaml`
- Marketdata freshness must gate strategies/execution: `docs/MARKETDATA_HEALTH_CONTRACT.md`
- Execution remains **disabled** by default (do not enable in automation).

