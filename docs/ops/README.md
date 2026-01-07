# Ops (AgentTrader v2)

This folder contains the operational documentation for running AgentTrader v2 safely in autonomous **observe-only** mode.

## Index

- **Agent mesh plan (single source of truth)**: `docs/ops/agent_mesh.md`
- **Reporting / readiness**: `docs/ops/reporting.md`
- **Runbooks**: `docs/ops/runbooks/`
- **Go/No-Go checklist (stub)**: `docs/ops/go_no_go.md`
- **Deploy guardrails (stub)**: `docs/ops/deploy_guardrails.md`
- **Disaster recovery plan (stub)**: `docs/ops/dr_plan.md`

## Quick commands (read-only)

- Pre-market snapshot:
  - `./scripts/ops_pre_market.sh`
- Post-market snapshot:
  - `./scripts/ops_post_market.sh`

## Safety reminders

- Kill-switch defaults to **HALTED** in k8s: `k8s/05-kill-switch-configmap.yaml`
- Marketdata freshness must gate strategies/execution: `docs/MARKETDATA_HEALTH_CONTRACT.md`
- Execution remains **disabled** by default (do not enable in automation).

