# CI Contract (Do Not Break)

This document records **CI assumptions** that must remain true. Changes that violate this contract are considered **CI regressions** even if they “work locally”.

## Source of truth

- **Primary**: `.github/workflows/ci.yml`
- **Secondary (guardrails invoked via `make guard`)**: `scripts/ci_safety_guard.sh`
- **Production lock validator (ops)**: `scripts/validate_production_lock.sh` + `ops/PRODUCTION_LOCK.md`

## Required scripts / commands

CI and CI-adjacent automation relies on the following entrypoints continuing to exist and remain compatible.

### Git-based scanners (workflow “Blockers” step)

CI runs `git grep` over tracked files to enforce:

- **Banned vendor references** (case-insensitive), including patterns like `supabase`, `postgrest`, `gotrue`
- **Secret material markers**, including PEM private keys and Google service-account JSON fields

**Contract**:

- `git` must be available in CI.
- These scans must remain **read-only** and **fail closed** (match ⇒ CI fails).
- Excluding `.github/workflows/**` is intentional (avoid self-matching the workflow).

### Backend dependency lock determinism

CI runs:

- `make lock-check`

`make lock-check` depends on:

- `Makefile` targets `lock-check` (and the underlying `pip-tools` invocation)
- Python (CI uses **3.12** via Actions)
- `backend/**/requirements.txt` sources and their corresponding `backend/**/requirements.lock` outputs

**Contract**:

- The `lock-check` target must continue to **diff** a freshly compiled lock against the committed lock(s) and fail if they differ.
- The lockfile set must include (at minimum) the paths referenced by CI caching:
  - `backend/requirements.lock`
  - `backend/strategy_service/requirements.lock`
  - `backend/risk_service/requirements.lock`
  - `backend/mission_control/requirements.lock`
  - `backend/execution_agent/requirements.lock`
  - `backend/strategy_engine/requirements.lock`

### Deployment report smoke test (no cluster required)

CI runs (from repo root):

- `python scripts/report_v2_deploy.py --skip-health --output-dir audit_artifacts_ci`
- then asserts these files exist:
  - `audit_artifacts_ci/deploy_report.md`
  - `audit_artifacts_ci/deploy_report.json`

**Contract**:

- `scripts/report_v2_deploy.py` must accept `--skip-health` and `--output-dir <dir>`.
- It must be **CI-safe**: no cluster required, no destructive actions, and should not require credentials.
- It must write the two output files above, under the requested output directory, on success.

### Backend compile check

CI runs:

- `python -m compileall backend`

**Contract**:

- All Python modules under `backend/` must be syntactically valid for the CI Python version.

### Intent logging schema check

CI runs:

- `python scripts/validate_intent_logging.py`

**Contract**:

- The script must remain CI-safe (no network, no credentials).
- It must validate that emitted intent logs contain the required keys and that sensitive values are **redacted**.

### Frontend install + build/typecheck

CI runs (working directory `frontend/`):

- `npm ci --no-audit --no-fund`
- then either `npm run build` (preferred) or `npm run typecheck`
  - CI checks for the presence of those scripts in `frontend/package.json`

CI caching expects:

- `frontend/package-lock.json`

**Contract**:

- `frontend/package.json` must exist and define at least one of:
  - `scripts.build`, or
  - `scripts.typecheck`
- `frontend/package-lock.json` must exist and be compatible with `npm ci`.

## Expected paths (must remain stable)

CI hard-codes these paths. Moving/renaming them is a breaking change unless CI is updated in the same PR.

- **Workflow file**: `.github/workflows/ci.yml`
- **Make target**: `Makefile` → `lock-check`
- **Backend lockfiles**: `backend/**/requirements.lock` (see list above)
- **CI artifacts output dir**: `audit_artifacts_ci/`
- **Deploy report outputs**:
  - `audit_artifacts_ci/deploy_report.md`
  - `audit_artifacts_ci/deploy_report.json`
- **Intent logging validator**: `scripts/validate_intent_logging.py`
- **Frontend working dir**: `frontend/`
- **Frontend lockfile**: `frontend/package-lock.json`

## Safety guard invariants

These invariants are **non-negotiable**. They are enforced via guard scripts and/or operational “production lock” policy, and should never be weakened casually.

### Script risk policy (`scripts/ci/enforce_script_risk_policy.py`)

CI enforces an explicit inventory of runnable scripts under `scripts/**` via:

- **Policy**: `scripts/ci/enforce_script_risk_policy.py` (read-only scanner)
- **Manifest**: `scripts/ci/script_risk_policy_manifest.json`

If CI fails this check:

- **Missing scripts in manifest**: add the new `scripts/...(.sh|.py)` path to the manifest with an appropriate `category`.
- **Extra manifest entries**: remove entries for scripts that were deleted or renamed.
- **Duplicate entries**: deduplicate the manifest so each script path appears once.
- **Invalid categories**: set `category` to one of: `ci`, `ops`, `deploy`, `dev`, `execution`.
- **Missing exec guard invocation (only when `requires_exec_guard: true`)**: ensure the script contains a kill-switch guard (e.g., `get_kill_switch_state` / `EXECUTION_HALTED`) or change the manifest entry to not require the guard if the script is not execution-capable.

### CI safety guard (`scripts/ci_safety_guard.sh`)

The guard is intended to be **read-only** and **fail-fast** if it detects:

- **No `:latest` image tags** in `k8s/` or `infra/`
- **No `AGENT_MODE=EXECUTE`** anywhere in committed code/config
- **Execution agents not scaled up** (execution-related manifests must not set `replicas: [1-9]`)

### Production lock invariants (`ops/PRODUCTION_LOCK.md` + validator)

Under the production lock, the following must remain true:

- **Execution is disabled by default**
  - Kill-switch defaults SAFE/HALTED (e.g. `EXECUTION_HALTED: "1"`)
  - Execution agent deployment exists but is **scaled to 0**
- **No `AGENT_MODE=EXECUTE`** in manifests/config (`k8s/`, `infra/`, `config/`, `configs/`)
- **No `:latest` tags** in deployment manifests
- **Required ops docs exist** (validator checks specific files under `docs/ops/`)

## Why `EXECUTE` is forbidden

`EXECUTE` is forbidden because this repository is **production-locked** and designed to be auditable and fail-safe:

- **Risk containment**: accidental enablement of trading execution is an unacceptable failure mode.
- **Operational safety**: execution pathways must remain scaffold-only and disabled unless a controlled unlock is performed.
- **Auditability/compliance**: enabling execution requires evidence, approvals, and an updated production lock artifact (see `ops/PRODUCTION_LOCK.md`).

In practice, this means:

- CI/guards must treat `AGENT_MODE=EXECUTE` as a **hard failure**.
- Any attempt to introduce “just for tests” execution toggles in committed code is a regression unless explicitly routed through the controlled unlock process.

## Making changes safely

If you must change any of the above:

- Update `.github/workflows/ci.yml` **in the same PR** as any path/entrypoint changes.
- Keep guard scripts **read-only** and **fail-closed**.
- If a change touches execution/kill-switch semantics, treat it as a **production-lock unlock** (see `ops/PRODUCTION_LOCK.md`).

