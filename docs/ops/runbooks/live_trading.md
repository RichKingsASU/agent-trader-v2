## Runbook: Live trading operations (controlled unlock only)

This runbook exists to **separate live trading procedures** from paper/observe-only operations.

### Default posture (locked)

Under the current baseline, live trading is **not permitted**:

- Production lock: `ops/PRODUCTION_LOCK.md`
- Default is observe-only and **execution is disabled**

If you are operating under the default lock, use `docs/ops/runbooks/paper_trading.md` and `RUNBOOK.md`.

---

## Preconditions (must be true before any live enablement is considered)

Live trading enablement is a **human-only** change control event. At minimum:

- Controlled unlock procedure is followed (evidence + approvals + new lock):
  - `ops/PRODUCTION_LOCK.md` (required)
- Rollback path is confirmed and rehearsed:
  - `docs/ops/rollback.md`
  - `ops/lkg/lkg_readme.md`
- Kill switch control is confirmed and reachable:
  - `docs/KILL_SWITCH.md`
- Marketdata freshness gate is passing and enforced:
  - `docs/MARKETDATA_HEALTH_CONTRACT.md`
- Runtime safety gates pass in CI:
  - `scripts/ci_safety_guard.sh` and `pytest`

Fail-closed rule: if any precondition is unknown, live trading is **NO-GO**.

---

## Live enablement principles (safety-first)

- **Kill switch stays HALTED unless explicitly changed via approved unlock**.
- Prefer a phased approach:
  - start with observe-only validation
  - then (if permitted) enable the smallest possible scope
- Any anomaly triggers immediate return to safe posture:
  - re-enable kill switch halt
  - rollback to LKG / prior revision

---

## Emergency actions (always permitted; restores safety)

- **Enable kill switch (halt execution)**:
  - `EXECUTION_HALTED=1` (see `docs/KILL_SWITCH.md`)
- **Rollback**:
  - Kubernetes: restore to LKG (`docs/ops/rollback.md`)
  - Cloud Run: route traffic back to known-good revision (`docs/ops/rollback.md`)

---

## References

- Incident response notes: `docs/ops/incident_response.md`
- Day 1 ops posture: `docs/ops/day1_ops.md`

