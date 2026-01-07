# Ops Docs (AgentTrader v2)

## Blueprint (auto-generated)

- **Blueprint**: `docs/BLUEPRINT.md`
- **Regenerate**:

```bash
./scripts/generate_blueprint.sh
```

This produces:
- `docs/BLUEPRINT.md`
- `audit_artifacts/blueprints/BLUEPRINT_<YYYYMMDD_HHMM>.md`

## Safety reminders

- Kill-switch defaults to **HALTED** in k8s: `k8s/05-kill-switch-configmap.yaml`
- Marketdata freshness must gate strategies/execution: `docs/MARKETDATA_HEALTH_CONTRACT.md`
- Execution remains **disabled** by default (do not enable in automation).

