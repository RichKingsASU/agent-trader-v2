# Go / No-Go (Trading Floor Posture) — Stub

This is a **read-only posture checklist** for AgentTrader v2. It does **not** enable trading execution.

## Go criteria (observe-only)

- `EXECUTION_HALTED=1` (kill-switch engaged) is confirmed in the runtime environment.
- Marketdata heartbeat is healthy (`/healthz` returns 200 with `ok=true` and acceptable age).
- `audit_artifacts/deploy_report.md` shows core services healthy (no crash loops, no ImagePullBackOff).
- Strategy runtime is stable (no repeated stale-marketdata refusals).

## No-Go triggers

- Any ambiguity about kill-switch state.
- Marketdata stale/unreachable.
- CrashLoopBackOff or persistent image pull failures on critical workloads.
- Evidence of unintended execution enablement.

## Evidence to attach

- Output of `./scripts/ops_pre_market.sh`
- `audit_artifacts/deploy_report.md`
- Any relevant pod logs/events snapshot from `audit_artifacts/ops_runs/`

