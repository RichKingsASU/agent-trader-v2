# AgentTrader v2 — Enterprise CI/CD Safety Gate Specification

## Purpose

This document defines **enterprise-grade CI/CD safety gates** for AgentTrader v2.
It standardizes **mandatory merge gates**, defines **required GitHub checks** (blocking vs advisory), and specifies an **emergency override** process with auditability.
It also defines a **release tagging policy** and **audit artifact retention** requirements.

## Scope

- **In scope**: repository CI (GitHub Actions), merge gates, release tags, CI audit artifacts, and policy enforcement for paper/shadow-only operation.
- **Out of scope**: actual live-trading enablement design (this repo is intentionally paper/shadow-only by default), broker onboarding, and production runtime policy engines outside CI.

## Safety model (core invariant)

AgentTrader v2 must remain **paper/shadow-only by default**:

- **Runtime hard lock**: startup must refuse non-paper trading unless a reviewed code change explicitly enables it.
- **No live endpoint connectivity**: code and config must not allow live broker endpoints in normal operation.
- **No “execute authority”**: committed configuration must not set `AGENT_MODE=EXECUTE`, and runtime must refuse it.

## Mandatory CI gates (must pass to merge)

### Gate A — Import hygiene (deterministic, no hidden runtime side effects)

**Goal**: prevent import-time crashes and fragile import patterns from reaching main/release.

**Policy requirements**
- All Python modules must be syntactically valid (`compileall`).
- Runtime entrypoints must be importable without requiring external services.
- “Runtime scope” must not introduce fragile import hacks (e.g., `sys.path` mutations).
- Avoid accidental relative-import misuse in non-package entrypoints.

**Implementation hooks (already present)**
- `python -m compileall .` (syntax integrity)
- `pip check` (dependency integrity)
- Absolute import discipline checks (flake8 ABS rules) for script-like entrypoints
- Runtime guardrails enforcement (`scripts/ci/check_python_runtime_guardrails.py` and/or `scripts/ci/check_ci_guardrail_enforcement.py`)
- Import smoke entrypoint exists: `backend/jobs/smoke_imports.py` (recommended as a build-time import gate target)
- Container build import gate script exists: `scripts/ci_import_gate.sh` (for Cloud Build / image pipelines)

**Pass criteria**
- No compile errors
- No new `sys.path` mutation in runtime scope
- Required import discipline checks pass
- (For image-based releases) import gate passes for the built image and declared module entrypoints

---

### Gate B — Exec guard enforcement (prevent accidental high-risk execution)

**Goal**: ensure no high-risk scripts or runtime modes can execute without explicit, auditable intent.

**Policy requirements**
- High-risk scripts must be inventoried and classified.
- If a script is classified as requiring an execution guard, it must include an exec-guard invocation.
- Runtime must refuse forbidden “authority” modes (e.g., `AGENT_MODE=EXECUTE`).

**Implementation hooks (already present)**
- Script inventory / categorization: `scripts/ci/script_risk_policy_manifest.json`
- Manifest enforcement: `scripts/ci/enforce_script_risk_policy.py`
- Runtime mode hard guard: `backend/common/agent_mode_guard.py` (refuse `AGENT_MODE=EXECUTE`, require explicit `TRADING_MODE`)
- CI config scan: `scripts/ci_safety_guard.sh` (forbids committed `AGENT_MODE=EXECUTE`)
- Script-side exec guard library: `scripts/lib/exec_guard.py` (refuses guarded scripts in CI / runtime-like env; requires explicit local unlock for `MUST_LOCK`)

**Pass criteria**
- Manifest matches tracked scripts (no missing/extra/duplicate entries; categories valid)
- Any script marked `requires_exec_guard: true` passes guard pattern enforcement
- No committed config sets `AGENT_MODE=EXECUTE`

---

### Gate C — Shadow-only confirmation (paper trading hard lock + shadow-mode fail-safe)

**Goal**: ensure merges/releases cannot silently degrade the “shadow/paper only” safety posture.

**Policy requirements**
- CI must **explicitly** set `TRADING_MODE=paper` for tests and builds.
- Runtime guard must fail closed if `TRADING_MODE` is missing/invalid.
- Shadow-mode logic must default to safe behavior on configuration errors (fail-safe to shadow-on).

**Implementation hooks (already present)**
- CI test hard lock: `tests/test_trading_mode_guardrail.py` (requires `TRADING_MODE=paper` in CI)
- Runtime hard lock: `backend/common/agent_mode_guard.py` (refuses missing/invalid `TRADING_MODE`, forbids execute authority)
- Shadow mode docs and behavior: `docs/SHADOW_MODE.md` (default shadow mode ON; fail-safe to shadow on errors)

**Pass criteria**
- All CI jobs that run tests set `TRADING_MODE=paper`
- Guardrail test passes
- No deployment config in-repo indicates execution authority or live trading intent

---

### Gate D — No live endpoint detection (prevent accidental connectivity to live brokers)

**Goal**: prevent code/config from pointing at live broker endpoints (or other live trading control planes).

**Policy requirements**
- Committed config must not embed live broker endpoints.
- Runtime must hard-fail if configured to a known live broker trading host (paper-only allowlist).
- CI must detect introduction of live endpoint strings or configurations in runtime scope.

**Implementation hooks (already present / partial)**
- Paper-only defaults exist in config (`APCA_API_BASE_URL` defaulting to `https://paper-api.alpaca.markets` in multiple components).
- CI config scan exists: `scripts/ci_safety_guard.sh` (currently covers `AGENT_MODE=EXECUTE`, scaled execution agent, image pinning).

**Enterprise requirement (must be implemented and enforced as a blocking check)**
- Add/maintain a **Live Endpoint Scan** check that fails if:
  - A committed value indicates live broker trading host (e.g., Alpaca live host) in runtime scope config
  - A new allowlist exception is added without security review

**Pass criteria**
- No live endpoints detected in runtime scope config/code (or in any “defaults”)
- Live endpoint allowlist remains paper-only unless explicitly authorized (see Emergency Override)

## Required GitHub checks (branch protection)

### Blocking checks (required to merge)

The following checks MUST be set as **required status checks** on `main` (and any protected release branches):

- **CI / Validate Runtime Integrity**
  - Runs `scripts/ci_safety_guard.sh` (enforces “no execute authority”, no scaled execution agent, etc.)
- **CI / Lint & Format**
  - Includes Python compile gate and Ops UI build gate
  - Must run with `TRADING_MODE=paper`
- **CI / Unit Tests**
  - Must run with `TRADING_MODE=paper`
  - Must include `tests/test_trading_mode_guardrail.py`
- **Guardrails (YAML + Bash + No :latest) / guardrails**
  - Runs `scripts/ci/guardrails.sh` (script risk policy, YAML syntax, bash guardrails, no `:latest`, runtime guardrails)
- **YAML validate / yaml-validate**
  - Yamllint + script risk policy fail-fast

If Cloud Build is used for release images, add a required check:
- **Import Gate (image)**
  - `scripts/ci_import_gate.sh <image_ref> <module>...` for each containerized service entrypoint module

### Advisory checks (non-blocking, but monitored)

Advisory checks MUST run but do not block merges by default (may be promoted to blocking as maturity increases):

- **Dependency vulnerability scan**
  - SBOM generation + vuln scan (pip/npm) with triage thresholds
- **Secret scanning**
  - Ensure no credentials/API keys are committed
- **License compliance**
  - OSS license policy checks
- **SAST**
  - CodeQL or equivalent, tuned for Python/TypeScript

## Emergency override procedure (audited “break-glass”)

Emergency override exists for **incident response** and **business continuity**, not convenience.

### When permitted

An override may be used only when **all** are true:
- A production incident requires immediate remediation (security, financial risk, availability).
- The change is minimal and targeted.
- A rollback path is defined.

### How it works (process)

- **Authorization**
  - Requires approval from **DevSecOps Lead (or delegate)** and **On-call Engineering Lead** (two-person rule).
- **Mechanism**
  - Use GitHub branch protection “admin override” / temporary required-check relaxation for the smallest window possible.
  - Alternatively, merge via a dedicated **Emergency** workflow path that:
    - Requires the two approvals above
    - Requires a linked incident ticket
    - Records a structured override justification in the merge commit message and release notes
- **Post-merge obligations (mandatory)**
  - Within 24 hours: open a follow-up PR restoring any relaxed gates and addressing root cause.
  - Attach CI logs, diffs, and incident timeline to audit artifacts (see retention policy).

### Minimum audit data for an override

- Incident ticket ID
- Approvers (2) + timestamps
- Checks bypassed + reason
- Commit SHA(s) merged
- Rollback instructions

## Release tagging policy

### Tag format

- **Annotated, signed tags** (preferred): `agenttrader-v2/vMAJOR.MINOR.PATCH`
  - Example: `agenttrader-v2/v2.4.1`
- **Pre-releases**: `agenttrader-v2/vMAJOR.MINOR.PATCH-rc.N`
  - Example: `agenttrader-v2/v2.4.1-rc.3`

### Tag creation rules

- Tags may only be created from:
  - `main` (for releases), or
  - `release/*` branches (for release candidates), if used
- Tag creation requires:
  - All **blocking checks** passing on the tagged commit
  - A changelog entry (or release notes) describing:
    - safety-relevant changes
    - config/schema changes
    - operational impact/rollout notes

### Provenance & immutability requirements

For each release tag, generate and retain:
- Build provenance (commit SHA, CI run ID, builder identity)
- Immutable artifact identifiers (container digests, not mutable tags)
- SBOM(s) for shipped services
- Attestations (SLSA-style) when available

## Audit artifact retention

### What to retain (minimum set)

For every CI run on `main` and every release candidate:
- Full logs for blocking checks
- `scripts/ci/script_risk_policy_manifest.json` snapshot (and diff)
- Output of `scripts/ci/enforce_script_risk_policy.py`
- Output of `scripts/ci_safety_guard.sh`
- YAML validation results
- Test results summary (including `TRADING_MODE` enforcement evidence)

For every **release tag**:
- All above, plus:
  - SBOM(s)
  - Vulnerability scan reports + triage decision record
  - Artifact digest list (images)
  - Deployment manifest snapshot (k8s/cloudrun/infra) used for the release

### Retention windows

- **CI on PR branches**: 30 days (default Actions retention acceptable)
- **CI on `main`**: 180 days minimum
- **Release artifacts + evidence**: 7 years (or per regulatory requirement), stored in an immutable bucket or equivalent WORM-capable store
- **Emergency override artifacts**: 7 years minimum

## Mapping: current repo checks to gates (traceability)

- **Import hygiene**
  - `Mandatory CI Gates` workflow: compile + `pip check` + import discipline + critical tests
  - `CI` workflow: compileall (plus UI build)
  - (Optional for releases) `scripts/ci_import_gate.sh` against built images
- **Exec guard enforcement**
  - `Guardrails` workflow: `scripts/ci/enforce_script_risk_policy.py`
  - `CI` workflow: `scripts/ci_safety_guard.sh` (committed config scan)
- **Shadow-only confirmation**
  - `CI` workflow env: `TRADING_MODE=paper` for lint/tests
  - `tests/test_trading_mode_guardrail.py`
  - Runtime: `backend/common/agent_mode_guard.py`
- **No live endpoint detection**
  - Runtime: paper-only defaults and URL hardening (broker base URL must remain paper-only)
  - CI: must include a dedicated live-endpoint scan for runtime scope config/code (enterprise requirement)

## Change control

Any change to:
- required checks,
- gate definitions,
- allowed runtime modes,
- broker endpoint allowlists,
- emergency override policy,

is a **security policy change** and requires DevSecOps review.

