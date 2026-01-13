## Runbook: Paper / Observe-only operations (default posture)

This runbook covers **paper trading / observe-only** operations. It is compatible with the production lock posture and is intended to be safe by default.

### Absolute safety rules

- **Do not enable trading execution**.
- Keep kill switch **HALTED**: `EXECUTION_HALTED=1` (see `docs/KILL_SWITCH.md`).
- Never set `AGENT_MODE=EXECUTE|LIVE` in committed config (CI enforces this).

### Scope

- Marketdata ingestion and health
- Strategy runtimes producing proposals/telemetry (no broker actions)
- Pub/Sub ingest/consume pipelines
- Ops UI / mission-control visibility

For data-plane incidents, use `RUNBOOK.md`.

---

## Preconditions (paper posture)

- `TRADING_MODE=paper` (runtime/environment; CI uses this posture for guardrails)
- Execution workloads remain off / halted:
  - Kubernetes: execution agent scaled to 0 and kill switch halted (see `ops/PRODUCTION_LOCK.md`)
  - Cloud Run: do not deploy/operate the execution engine in a way that can place broker orders

---

## Start-of-day checklist (paper / observe-only)

- [ ] Confirm kill switch is halted (`EXECUTION_HALTED=1`):
  - Kubernetes: `kubectl -n trading-floor get cm agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'`
- [ ] Confirm marketdata freshness gate is healthy:
  - `GET /healthz` is 200 with `ok=true` (see `docs/MARKETDATA_HEALTH_CONTRACT.md`)
- [ ] Confirm no CrashLoopBackOff / ImagePullBackOff on critical workloads:
  - Runbook mapping: `docs/ops/runbooks/crashloop_backoff.md`, `docs/ops/runbooks/image_pull_backoff.md`
- [ ] Generate evidence artifacts (read-only):
  - `docs/ops/day1_ops.md` describes the expected artifacts and cadence.

---

## Safe operational actions (allowed)

- **Pause ingestion** to stop blast radius (no redeploy):
  - Use `INGEST_ENABLED=0` (see `docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md`)
- **Rollback / restore** to known-good:
  - Use `docs/ops/rollback.md` (prefer Kubernetes LKG restore)
- **Drain Pub/Sub backlog**:
  - Follow `RUNBOOK.md` (do not “fix” by enabling execution)

---

## Post-incident / end-of-day

- [ ] Capture artifacts (`audit_artifacts/…`) and link to the incident timeline.
- [ ] Verify kill switch still halted.
- [ ] If a rollback occurred, preserve the evidence:
  - deploy report + readiness report + relevant `ops_runs/` snapshot directory

