# Deploy guardrails — Stub

Guardrails for changes to AgentTrader v2 that preserve safety, auditability, and “observe-only by default” posture.

## Hard rules

- No automation may enable execution (`execution-agent` must remain OFF by default).
- No deployment may remove or bypass:
  - kill-switch enforcement (`EXECUTION_HALTED`)
  - marketdata freshness gating (`/healthz` contract)

## Required pre-deploy checks

- `./scripts/preflight.sh` (local build/compile checks; may be heavy)
- `./scripts/report_v2_deploy.sh --skip-health` (cluster posture snapshot, read-only)
- Secrets are provided only via Secret Manager / mounted files (no plaintext in manifests).

## Required post-deploy checks

- `./scripts/ops_pre_market.sh` (or `./scripts/ops_post_market.sh`) generates audit artifacts.
- Marketdata `/healthz` returns 200 during market hours.

