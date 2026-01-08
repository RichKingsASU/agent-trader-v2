## CI Guardrails v3 (Blocking + Advisory)

This document defines **CI guardrails** for this repository: fast, deterministic, **read-only** checks that prevent avoidable outages, supply-chain surprises, and safety regressions.

It is intended to be compatible with (and complementary to) the existing CI contract and guard scripts:

- **CI contract**: `docs/CI_CONTRACT.md`
- **Existing guardrails script**: `scripts/ci/guardrails.sh` (YAML syntax, bash guardrails, block `:latest`)
- **Existing guardrails workflow**: `.github/workflows/guardrails.yml`

> Note: A file named `ci_guardrails_v2.md` was not present in this workspace at time of writing. This v3 is drafted to match the repo’s current CI contract (`docs/CI_CONTRACT.md`) and the implemented guardrails under `scripts/ci/`.

### Goals

- **Fail closed on safety / determinism regressions**: prevent changes that can enable unsafe behavior, break deployability, or make builds non-repeatable.
- **Be fast and actionable**: keep guardrails tight, with precise file/line output and clear remediation steps.
- **Separate “must pass” from “should improve”**: blocking checks protect invariants; advisory checks guide quality without stopping work.

### Definitions

- **Blocking checks**: required to pass before merge. These are deterministic and tied to correctness/safety/reproducibility.
- **Advisory checks**: do not block merge, but produce annotations/reports. These track hygiene, upcoming migrations, and longer-term improvements.

---

## Baseline (already present today)

This section documents what currently exists so new proposals don’t duplicate effort.

### Blocking (today)

- **YAML syntax validation** across tracked `*.yml/*.yaml` (`scripts/ci/validate_yaml_syntax.py`).
- **Bash guardrails**:
  - bash parse check (`bash -n`) for tracked `*.sh`
  - custom variable-usage pitfalls scan (`scripts/ci/check_bash_vars.py`)
  - ShellCheck for CI bash entrypoints (`scripts/ci/check_bash_guardrails.sh`)
- **Block floating container tags `:latest`** in runnable YAML and Dockerfiles (`scripts/ci/check_no_latest_tags.py`).
- **Backend dependency lock determinism** (CI contract): `make lock-check` must fail if `backend/**/requirements.lock` are stale.
- **Backend compile check** (CI contract): `python -m compileall backend`.
- **Contract / policy guards** (CI contract): banned vendor refs, secret material markers, “no EXECUTE mode”, etc.

---

## Proposed additional CI checks (v3)

The following are **proposals only** (no pipeline edits in this change). They are grouped by whether they should be blocking vs advisory.

### Blocking checks (proposed)

#### 1) Schema validation (fail closed)

**Why**: YAML syntax passing is not enough. Schema validation catches invalid fields, wrong types, missing required properties, and breaking contract changes earlier.

**Proposed scope**:

- **Kubernetes schema validation** for `k8s/**` (and any other deploy manifests) in addition to `kubectl apply --dry-run=client`.
  - Recommended tool: `kubeconform` (or equivalent) with pinned Kubernetes version schemas.
  - Behavior:
    - Fail if any manifest fails schema validation.
    - Handle CRDs explicitly:
      - If CRDs are used: add CRD schemas to validation inputs (preferred), or
      - Temporarily allow missing schemas with a tracked allowlist (migration mode).
- **OpenAPI spec validation** for `docs/ops/ops_api_contract.openapi.yaml`.
  - Recommended tools: `swagger-cli validate`, `openapi-generator validate`, or `spectral` in “validate” mode.
  - Behavior:
    - Fail if the spec is not parseable, has broken `$ref`s, or violates OpenAPI structural rules.

**Blocking acceptance criteria**:

- The schema validator(s) run without network access and without credentials.
- Output includes `file:line` and a human-readable error for quick fixes.

#### 2) Docker image reproducibility (fail closed on nondeterminism)

**Why**: Mutable build inputs (floating base tags, unpinned packages, non-repeatable build steps) cause “same commit, different artifact” failures and complicate incident response/auditing.

**Proposed approach (phased, but ultimately blocking)**:

- **Enforce immutable base images for Dockerfiles**:
  - Block `FROM <image>:<tag>` unless it is pinned by digest (`FROM <image>@sha256:...`), at least for production-deployed images.
  - Rationale: even versioned tags (e.g. `python:3.12-slim`) can be republished.
- **Enforce immutable runtime image references** in deploy manifests:
  - Prefer `image: repo/name@sha256:...` (digest) over tags.
  - Keep `:latest` banned (already enforced), but extend coverage to other floating tags where practical.
- **Reproducibility test build (same inputs ⇒ same image)**:
  - Build the same Dockerfile twice in a clean context with:
    - `--no-cache` and `--pull`
    - fixed build args (no wall-clock timestamps)
    - a stable `SOURCE_DATE_EPOCH` derived from the commit timestamp
  - Compare resulting image IDs/digests; **fail if they differ**.

**Notes / constraints**:

- Some images intentionally embed build metadata (e.g., build time). For reproducibility, those values must be **derived deterministically** (e.g., from git commit time) or removed from the digest-impacting surface.
- If immediate blocking is too disruptive, start as advisory (see below) and promote to blocking once Dockerfiles are made deterministic.

#### 3) Dependency drift (fail closed when source-of-truth diverges)

**Why**: Drift between dependency manifests and lockfiles produces “works locally” installs, non-reproducible builds, and unexpected prod behavior.

**Proposed scope**:

- **Expand lock determinism beyond `backend/**`**:
  - Identify deployable Python components outside backend (examples in this repo include `functions/requirements.txt`, `cloudrun_consumer/requirements.txt`, and `backend/ingestion/requirements.txt`).
  - Standardize on a lock mechanism (e.g., `pip-tools`, `uv lock`, or equivalent) per component.
  - Add a “lock-check” equivalent that recompiles locks in CI and fails on diff.
- **Manifest/lock coherence checks** (lightweight, fast):
  - If `*/requirements.txt` changes, the corresponding lockfile must change in the same PR.
  - If a lockfile changes without its source manifest changing, require an explicit rationale (or block).
- **Node lock determinism** (where applicable):
  - Require a lockfile (`package-lock.json`/`pnpm-lock.yaml`/`yarn.lock`) for each buildable Node package.
  - Run the package manager’s immutable install mode (`npm ci` / `pnpm i --frozen-lockfile` / `yarn --immutable`) and fail on drift.

---

### Advisory checks (proposed)

#### 1) Schema validation (visibility + change impact)

- **Breaking-change detection for API contracts**:
  - Run an OpenAPI diff against the base branch and **warn** on breaking changes (removed fields, tightened enums, requiredness changes, etc.).
  - Recommended tools: `openapi-diff`, `oasdiff`, or `spectral` rules tuned for backwards compatibility.
- **Schema coverage report**:
  - Warn when new contract-like files are introduced without validation (e.g., a new `*.openapi.yaml` without being added to the validator list).

#### 2) Docker image reproducibility (migration + supply chain hygiene)

- **“Reproducibility dry-run” report**:
  - Attempt the two-build comparison and report drift reasons (timestamps, file ordering, package manager nondeterminism).
  - Useful during migration before enforcing as blocking.
- **SBOM + vulnerability scan** (advisory by default):
  - Generate SBOMs (e.g., Syft) and run vulnerability scanning (e.g., Grype/Trivy).
  - Keep non-blocking initially to avoid noisy CVE churn; promote selectively for high-severity, exploitable findings.
- **Dockerfile best-practice lint**:
  - Warn on patterns that undermine reproducibility (unpinned `apt-get install`, `pip install` without locks, etc.).

#### 3) Dependency drift (upgrade visibility)

- **Outdated dependency reporting**:
  - `pip`/`npm` “outdated” reports for awareness, not enforcement.
- **License policy scan**:
  - Identify newly introduced disallowed licenses; keep advisory unless/until policy hardens.

---

## Operating model

### Ownership

- **Blocking checks**: owned by the platform/DevOps team; changes require the same rigor as production-safety policy (`docs/CI_CONTRACT.md`).
- **Advisory checks**: owned jointly; teams can iterate quickly, but must keep signal-to-noise high.

### Promotion policy (advisory → blocking)

Promote an advisory check to blocking when:

- It is deterministic in CI (no flaky external calls, no time-based nondeterminism).
- It has clear remediation steps.
- The repo has been migrated to comply (or has explicit allowlists with expirations).

