# Repo cleanup plan (non-destructive)

## Goals

- **Reduce repo-root noise**: keep root focused on entrypoints (`README.md`, `Makefile`, top-level config).
- **Preserve auditability**: do not delete history; move stale/one-off artifacts into `archive/` with provenance.
- **Make docs navigable**: treat `docs/` as the canonical long-lived documentation tree.
- **Make scripts discoverable**: group scripts by intent (CI, dev, ops, deploy, data, demos) and clearly mark deprecated/unsafe helpers.

## Current observations (root scan)

- **Root contains 116 Markdown files**. Many look like delivery artifacts or “phase completion / implementation summary / verification” snapshots (high churn, low ongoing value).
- **A tracked log exists**: `maestro_bridge.log` (empty in this workspace, but still violates the stated guardrail “Logs (*.log) must never be tracked” in `REPO_GUARDRAILS.md`).
- **Root has 7 shell scripts**; several are placeholders or run background processes (`market_open.sh`, `market_close.sh`) or auto-commit/push (`daily-git-sync.sh`).
- **CI explicitly validates repo-root `cloudbuild*.yaml`** (see `.github/workflows/ci.yml`), so moving those needs coordination.

## Proposed end-state layout (high level)

### `archive/` (historical / one-off artifacts)

Use `archive/` for files that are valuable as historical record but should not be “front page” material.

Recommended structure:

- `archive/phases/` (phase-specific artifacts)
- `archive/implementation_summaries/`
- `archive/verification_reports/`
- `archive/visual_summaries/`
- `archive/delivery/`
- `archive/templates/` (templates that are not actively maintained)
- `archive/logs/` (tracked logs should be removed from git in a later step; until then, keep them quarantined here)
- `archive/wireframes/`
- `archive/ops_snapshots/` (older generated audit artifacts beyond the “current” set)

### `docs/` (canonical documentation)

Keep `docs/` as the single place where “how the system works” and “how to operate it” lives.

Recommended additions (folders; keep existing content as-is):

- `docs/architecture/`
- `docs/deployment/`
- `docs/data/` (Firestore schema/model, TTL, etc.)
- `docs/security/`
- `docs/features/` (whale flow, analytics, backtesting, etc.)

Also recommended:

- `docs/README.md` (a docs index) that links to the above categories and the existing `docs/ops/`, `docs/runbooks/`, `docs/trading/`, etc.

### `scripts/` (operational tooling)

Current `scripts/` is already the right home, but it’s flat and mixes concerns. Keep existing behavior, but group by intent:

- `scripts/ci/` (already exists; keep)
- `scripts/dev/` (local dev, mock feeds)
- `scripts/deploy/` (deploy + rollout)
- `scripts/ops/` (readiness, status, logs)
- `scripts/k8s/` (kubectl helpers, YAML validation)
- `scripts/data/` (seeders, backfills, replay tools)
- `scripts/demo/` (demos, examples)
- `scripts/verify/` (verification scripts)
- `scripts/_deprecated/` (dangerous or legacy scripts; keep executable bits but mark clearly)

## Concrete moves (proposal only; do not delete anything)

### A) Repo-root artifacts → `archive/`

These are strongly suggested for archiving because they look like “delivery snapshots” rather than living docs:

- **Phase artifacts**: `PHASE*.md` → `archive/phases/`
- **Completion artifacts**: `*_COMPLETE*.md`, `*_COMPLETION_*.md` → `archive/implementation_summaries/`
- **Implementation summaries**: `*_IMPLEMENTATION_SUMMARY.md`, `IMPLEMENTATION_*.md` → `archive/implementation_summaries/`
- **Verification reports**: `*_VERIFICATION*.md`, `ARCHITECTURE_VERIFICATION_*.md` → `archive/verification_reports/`
- **Visual summaries**: `*_VISUAL_*.md`, `*_DIAGRAM*.md` → `archive/visual_summaries/`
- **Delivery summaries**: `*_DELIVERY*.md`, `DELIVERY_SUMMARY.*` → `archive/delivery/`
- **Wireframes**: `dashboard_wireframe.md` → `archive/wireframes/`
- **Logs**: `maestro_bridge.log` → `archive/logs/` (and later: stop tracking `*.log` per guardrails)

Rationale:

- **These files are valuable history** (what was done, when, by whom) but **create high cognitive load** when kept at repo root.
- Many include “Implementation Complete”, “Status”, “Date”, and long checklists—great for audit trail, poor as canonical documentation.

### B) Repo-root docs → `docs/` (when they are “living docs”)

Some root docs look more like canonical references and should be promoted under `docs/` (with redirects or link updates):

- **Governance / guardrails**: `REPO_GUARDRAILS.md` → `docs/governance/repo_guardrails.md`
- **Tenancy / multi-tenant**: `TENANCY_MODEL.md`, `MULTI_TENANT_MIGRATION.md` → `docs/architecture/tenancy/`
- **Deployment**: `DEPLOYMENT.md`, `PRODUCTION_DEPLOYMENT_GUIDE.md` → `docs/deployment/`
- **Data model / Firestore**: `firestore_schema.md`, `FIRESTORE_DATA_MODEL.md`, `firestore_ttl.md` → `docs/data/firestore/`
- **Feature docs that should be discoverable** (examples):
  - `WHALE_FLOW_INDEX.md`, `WHALE_FLOW_QUICK_START.md` → `docs/features/whale_flow/`
  - `BACKTESTING_GUIDE.md`, `BACKTESTING_QUICK_START.md` → `docs/features/backtesting/`
  - `ANALYTICS_QUICK_START.md` → `docs/features/analytics/`

Rationale:

- These read as “how to use/operate/build”, not “what we delivered on date X”.

### C) Repo-root scripts → `scripts/` (or `archive/`)

Root scripts should not live at root; they also bypass Makefile conventions and may be unsafe:

- **Risky automation**:
  - `daily-git-sync.sh` → `scripts/_deprecated/daily-git-sync.sh` (auto-commit + push; high blast radius)
  - `agenttrader_agents.sh` → `scripts/_deprecated/agenttrader_agents.sh` (depends on local `.venv/` and calls `daily-git-sync.sh`)
- **Placeholder / background-process scripts**:
  - `market_open.sh`, `market_close.sh`, `pre_market.sh`, `post_market.sh` → `archive/templates/ops_day_parts/`
    - These currently start background processes and reference paths that may not exist in all environments.
- **Template with embedded example identity**:
  - `create_scheduler_job_template.sh` → `archive/templates/gcp/create_scheduler_job_template.sh`
    - Follow-up: convert to a `.example` file and remove hard-coded service account email in a future change.

### D) Keep repo-root `cloudbuild*.yaml` (for now)

Because CI currently includes:

- **Repo-root Cloud Build configs** via `cloudbuild*.yaml` globbing (see `.github/workflows/ci.yml`)

…the simplest cleanup plan is:

- **Keep `cloudbuild*.yaml` at root as canonical** until CI/scripts are updated.
- If there are duplicates under `infra/`, pick one canonical source-of-truth later and either:
  - generate the other copies, or
  - move to `infra/cloudbuild/` and adjust CI and deploy scripts accordingly.

## Script taxonomy plan (proposal)

Without changing behavior, move files under `scripts/` into subfolders and update references (Make targets + CI scripts):

- **CI**: keep `scripts/ci/` as-is; ensure any top-level CI scripts remain callable (or provide thin wrappers).
- **Ops**: `kubectl_*.sh`, `readiness_check.sh`, `rollout_guard.sh`, `predeploy_guard.sh`, `verify_*.sh` → `scripts/ops/` + `scripts/verify/`
- **Deploy**: `deploy_v2.sh`, `deploy_v2_legacy.sh`, `setup_cloud_run_*.sh`, `setup_cloud_scheduler_*.sh` → `scripts/deploy/`
- **Dev**: `dev_*.sh`, `mock_*_feed.py`, `run-*-dev.sh` → `scripts/dev/`
- **Data / replay**: `seed_*.py`, `populate_*.py`, `replay_*.py`, `run_backtest_example.py` → `scripts/data/`
- **Demos**: `demo_*.py`, `ledger_pnl_demo.py` → `scripts/demo/`

Additionally:

- Add `scripts/README.md` describing:
  - **what is safe to run locally**
  - **what is read-only**
  - **what requires cloud credentials**
  - **what is deprecated**

## Execution plan (safe, incremental)

1. **Create `archive/` skeleton** (empty dirs + README explaining the intent).
2. **Move obvious historical artifacts** (phase/completion/verification/visual/delivery) into `archive/` using `git mv`.
3. **Promote canonical docs into `docs/`** and update inbound links (from `README.md`, `docs/*`, and any scripts referencing doc paths).
4. **Quarantine logs and placeholders**:
   - move `maestro_bridge.log` into `archive/logs/`
   - follow-up change: stop tracking `*.log` (per guardrails) and add/verify `.gitignore` coverage.
5. **Refactor scripts into subfolders** and update:
   - `Makefile` targets
   - CI workflows / scripts that reference old paths
6. **Validate**:
   - run the existing Make targets (`make guard`, `make ci-validate`) and CI checks.

## “Do not move” shortlist (until proven safe)

- **Files referenced by CI**: `cloudbuild*.yaml`, `scripts/validate_cloudbuild_configs.sh`, `scripts/validate_ci_layout.sh`, `scripts/ci_safety_guard.sh`, `scripts/ci/**`.
- **Makefile entrypoints**: scripts invoked by `make dev`, `make deploy`, `make report`, `make readiness`, `make logs`, `make scale`, etc.
- **Audit trail artifacts**: keep `audit_artifacts/` as the canonical “current” output location; archive older snapshots if it grows.

