# Disaster Recovery (DR) Plan — Stub

This is a minimal DR outline for AgentTrader v2. Expand it for your infrastructure and compliance needs.

## Objectives

- Preserve **halt posture** (no execution) during incidents.
- Restore **marketdata heartbeat** and **strategy observe-only** functionality first.
- Keep an auditable record of actions and system state (`audit_artifacts/`).

## DR priorities (order)

1. **Confirm execution is halted**
   - Verify `EXECUTION_HALTED=1` (k8s ConfigMap / env) is active.
2. **Restore marketdata**
   - Restore `marketdata-mcp-server` and/or `market-ingest-service`.
   - Validate `GET /healthz` freshness contract.
3. **Restore strategy runtime**
   - Ensure strategies refuse to run on stale marketdata.
4. **Restore APIs and reporting**
   - Strategy service, reporting scripts, dashboards.

## Backups / state

- Define your source of truth for:
  - Strategy configs
  - Paper order ledgers / logs
  - Analytics datasets
  - Firestore collections used for heartbeats

## Post-incident

- Save `audit_artifacts/ops_runs/*` and `audit_artifacts/deploy_report.*`.
- Add a short incident report (timeline, root cause, preventative actions).

