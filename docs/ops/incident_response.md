## Incident response notes (AgentTrader v2)

This document is a **repo-local** incident response guide: how to triage safely, what evidence to capture, and which runbooks to follow.

### Absolute safety rule

- **Do not enable trading execution** during incident response. Preserve the default posture: `EXECUTION_HALTED=1` (see `docs/KILL_SWITCH.md` and `ops/PRODUCTION_LOCK.md`).

---

## A) Triage principles (fail-closed)

- **Stop the blast radius first**:
  - Pause ingestion (`INGEST_ENABLED=0`) if the producer is flooding or publishing poison (see `docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md`).
  - Keep execution halted even if data plane is degraded.
- **Assume at-least-once delivery**:
  - Pub/Sub redelivery and out-of-order delivery are normal; treat non-idempotent behavior as a regression (see `docs/dlq_and_retries.md`).
- **Prefer rollback over roll-forward** when the failure correlates with a deployment/regression.

---

## B) Severity guidance (repo-oriented)

Use your org’s incident policy as the source of truth; the mapping below is operationally useful for this repo:

- **Sev-0 (safety breach)**:
  - Any evidence of unintended execution enablement (e.g. `AGENT_MODE=EXECUTE|LIVE`, kill-switch not halted, execution workloads scaled > 0).
  - Immediate escalation path is defined in `ops/PRODUCTION_LOCK.md`.

- **Sev-1 (data plane outage during market hours)**:
  - Marketdata freshness gate failing (`/healthz` stale) during market hours.
  - Pub/Sub backlog oldest age growing rapidly; DLQ growth indicating poison or consumer failure.

- **Sev-2 (degraded)**:
  - Elevated error rates but system still processing; slow drain of backlog.

- **Sev-3 (informational / maintenance)**:
  - Non-critical UI outage (Ops UI) while mission-control and core services remain healthy.

---

## C) Evidence to capture (minimum viable)

### Always capture

- **What changed**:
  - commit SHA / build ID / image digest (for k8s: pinned digests; for Cloud Run: revision id).
- **What broke**:
  - error codes, timestamps (UTC), impacted service/subscription/topic.

### Repo-native artifacts (preferred)

Capture and retain:

- `audit_artifacts/deploy_report.{md,json}` (current deployment snapshot)
- `audit_artifacts/readiness_report.{md,json}` (GO/NO-GO posture evidence)
- `audit_artifacts/ops_runs/<UTC>_*/` (pre/post market and ad-hoc snapshots)
- `ops/lkg/` (if rollback is via LKG restore; treat as release evidence)

---

## D) Runbook index (first responders)

### Data plane (ingest → Pub/Sub → consumer)

- Primary: `RUNBOOK.md` (ingestor/consumer/backlog)
- DLQ + retry semantics: `docs/dlq_and_retries.md`
- Ingest pause switch details: `docs/INGEST_ENABLED_KILL_SWITCH_FLOW.md`

### Kubernetes operational runbooks

- Crash loops: `docs/ops/runbooks/crashloop_backoff.md`, `docs/ops/runbooks/crashloop.md`
- Image pull issues: `docs/ops/runbooks/image_pull_backoff.md`
- Resource pressure: `docs/ops/runbooks/resource_pressure.md`
- Marketdata stale: `docs/ops/runbooks/marketdata_stale.md`
- Strategy halted: `docs/ops/runbooks/strategy_engine_halted.md`

### Rollback / restore

- Rollback procedures: `docs/ops/rollback.md`
- Disaster recovery + backups: `docs/ops/disaster_recovery.md`

---

## E) Communications + safety logging

- Record operator actions with timestamps (UTC) and rationale.
- Preserve logs and artifacts needed to prove the safety posture remained intact:
  - `EXECUTION_HALTED` stayed enabled
  - no execution workloads were scaled/activated
  - no config changes enabled `AGENT_MODE=EXECUTE|LIVE`

