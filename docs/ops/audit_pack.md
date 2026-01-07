# Audit Pack (Evidence Retention)

An audit pack is the minimum evidence bundle required for:

- controlled unlocks (see `ops/PRODUCTION_LOCK.md`)
- production deployments/releases
- post-incident review

## Contents (minimum)

- **Readiness output** (timestamp, git sha, environment scope)
- **Manifest diff** (what changed across `k8s/` and `infra/`)
- **Configuration snapshot** for safety controls (kill-switch defaults)
- **Approval record** (completed template from `docs/ops/go_no_go.md`)

## Retention expectations

- Audit artifacts must be stored durably and referenced by index.
- Prefer storing in `audit_artifacts/` (or an external immutable store) with a committed index that points to the canonical location.

