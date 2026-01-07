# AgentTrader v2 — Production Lock (v2 Freeze)

## Lock metadata

- **lock_timestamp_utc**: 2026-01-07T01:14:27Z
- **repo_id**: RichKingsASU/agent-trader-v2
- **git_sha**: 0922f0200658729dd3b583cad65cd859752f2cee
- **build_id**: N/A (not provided in this lock)
- **clusters_targeted**:
  - **Kubernetes (GKE)**: `trading-floor` namespace (see `k8s/`)
  - **Cloud Run**: service templates for `execution-engine` and `market-ingest` (see `infra/cloudrun/services/`)

## Non-negotiable safety statements (locked)

- **Execution is DISABLED**.
  - **Kubernetes default**: `k8s/05-kill-switch-configmap.yaml` sets `EXECUTION_HALTED: "1"` (HALTED).
- **AGENT_MODE defaults OFF**.
  - No repository manifests may set `AGENT_MODE=EXECUTE`.
- **Kill-switch defaults SAFE**.
  - “SAFE” = **HALTED** (`EXECUTION_HALTED="1"`). Any change away from HALTED requires a controlled unlock.

## Locked components (baseline scope)

These components are frozen as the v2 operational baseline.

- **marketdata-mcp-server**
  - k8s deployment/service: `k8s/20-marketdata-mcp-server-deployment-and-service.yaml`
  - implementation: `mcp/server/*`
- **strategy-engine**
  - k8s statefulsets: `k8s/10-gamma-strategy-statefulset.yaml`, `k8s/11-whale-strategy-statefulset.yaml`
  - runtime: `backend/` (strategy runtime container references are pinned in k8s manifests)
- **execution-agent (disabled)**
  - **No execution agent workload is deployed by default** (only identity wiring exists under `k8s/serviceaccounts/`).
  - Kill-switch default is **HALTED**.
- **mission-control**
  - operational control-plane docs + runbooks in `docs/` (no production deployment changes allowed without unlock)
- **ops-ui**
  - `frontend/` (read-only operational UX under this lock; changes require unlock)

## Locked guarantees (must remain true)

- **No `:latest` container image tags in deployment manifests**
  - Applies at minimum to `k8s/` and `infra/cloudrun/**.yaml`.
- **Identity + intent logging is mandatory**
  - Any autonomous agent action must be attributable (who/what/why/inputs/outputs).
- **Health contracts are enforced**
  - Services must adhere to documented health/readiness contracts (e.g. `docs/MARKETDATA_HEALTH_CONTRACT.md`).
- **Readiness + deploy reports are required**
  - Readiness evidence must be generated and retained before any controlled unlock/deploy.
- **Audit artifacts are retained**
  - Audit packs, indexes, and verification outputs must be durable and reviewable (see `docs/ops/audit_pack.md`).

## Controlled unlock procedure (required for any change in locked scope)

### Unlock triggers (requires controlled unlock)

- Enabling any form of **EXECUTE** behavior (including setting `AGENT_MODE=EXECUTE`)
- Changing kill-switch defaults away from **HALTED/SAFE**
- Adding new agents, services, or production workloads (k8s/Cloud Run) that can influence execution

### Required evidence (must be produced and committed)

- **Readiness report** (current timestamp, git sha, environment scope)
- **Audit index** (artifact listing + hashes/paths)
- **Approval template filled** (human sign-offs captured in-repo)

### Required steps (the only allowed process)

- Create a **new branch** for the unlock (no direct changes on the locked baseline branch).
- Commit the **evidence artifacts** and **approvals** first.
- Apply the change behind explicit configuration gates (no implicit behavior).
- Generate a **new production lock artifact**:
  - update `ops/PRODUCTION_LOCK.md` with new timestamp/sha/evidence pointers
  - re-run validation (`scripts/validate_production_lock.sh`)
- Tag a new lock (`scripts/tag_production_lock.sh`) after validation passes.

## Autonomy readiness review (v2)

### What agents may do autonomously

- Run readiness checks and surface results (no state mutation in prod)
- Generate/refresh reports (readiness, audit packs, deployment diffs)
- Capture “LKG” references (last-known-good identifiers) as **evidence**
- Emit change proposals (PR-ready text, diffs, or plans) for human review

### What agents must never do

- Change `AGENT_MODE` (especially to `EXECUTE`) anywhere
- Flip the kill-switch or alter its default safety posture
- Deploy to production, scale production workloads, or apply manifests to prod

### Human-only actions

- Approving any controlled unlock (sign-offs)
- Any production deploy/release operation
- Any change that enables execution or alters kill-switch defaults

