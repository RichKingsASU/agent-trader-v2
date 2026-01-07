## AgentTrader v2 — Pre-Deploy Guardrails + Build Fingerprint

This repo enforces **deterministic, auditable deployments** by combining:

- **Build fingerprinting** (containers self-identify in logs and health responses)
- **Pre-deploy guardrails** (refuse unsafe or drifted manifests before apply)
- **No-footguns policy** (strictly no `:latest` in Kubernetes manifests)

---

## Build fingerprint (what it is)

Every v2 container exposes a small identity payload:

- `repo_id`: always `agent-trader-v2`
- `git_sha`: from `GIT_SHA` (or `unknown`)
- `build_id`: from `BUILD_ID` (or `unknown`)
- `image_ref`: from `IMAGE_REF` (or `unknown`)
- `build_time_utc`: from `BUILD_TIME_UTC` (or `unknown`)

On startup, each service emits **one structured log line**:

- `intent_type="build_fingerprint"`
- plus the fields above

Health endpoints include the same fields:

- `/health` (legacy)
- `/healthz` (institutional convention)

Implementation lives in `backend/observability/build_fingerprint.py`.

---

## Predeploy guard (how to run)

From repo root:

```bash
./scripts/predeploy_guard.sh --namespace trading-floor --k8s-dir k8s/
```

If you are intentionally working with images that cannot be validated (not recommended):

```bash
./scripts/predeploy_guard.sh --namespace trading-floor --k8s-dir k8s/ --allow-unknown-images
```

---

## What the guard checks

- **Cluster safety**
  - Refuses to run if current `kubectl` context is not the expected one.
  - Expected context can be provided via `--expected-context` or inferred from `gcloud config` when available.

- **Repo identity / drift prevention**
  - Every manifest file must include `agenttrader.dev/repo_id: agent-trader-v2`.

- **No unsafe agent mode**
  - Refuses if any manifest sets `AGENT_MODE=EXECUTE`.

- **No `:latest` anywhere**
  - Refuses if any `image:` line in `k8s/` uses `:latest`.
  - Also refuses `:dev` and missing/empty tags (no implicit latest).

- **Image existence (fail-safe)**
  - Parses all `image:` references in `k8s/` and verifies they exist.
  - Uses `gcloud artifacts docker images describe` when available; otherwise falls back to `docker manifest inspect`.
  - If existence cannot be validated, the guard **fails by default** unless `--allow-unknown-images` is provided.

---

## How to fix common failures

- **Context mismatch**
  - Confirm context: `kubectl config current-context`
  - Provide expected context explicitly:

```bash
./scripts/predeploy_guard.sh --expected-context gke_<project>_<location>_<cluster>
```

- **Missing repo label**
  - Add the label to affected manifests:
    - `agenttrader.dev/repo_id: agent-trader-v2`

- **Forbidden `AGENT_MODE=EXECUTE`**
  - Remove it (default must be non-executing).
  - If you need gating, use safe modes (e.g., simulate/dry-run) and keep live execution disabled by default.

- **Forbidden image tag (`:latest`, `:dev`, empty)**
  - Replace with an immutable tag or digest:
    - Prefer `:<git-sha>` or `@sha256:<digest>`

- **Image not found**
  - Build/push the image to the registry referenced by the manifest.
  - Ensure you are looking in the correct GCP project / Artifact Registry repository.

---

## Deploy wrapper

Use the wrapper to run the guard and then deploy deterministically:

```bash
./scripts/deploy_v2.sh --namespace trading-floor --k8s-dir k8s/
```

Strict rule: **no `:latest` anywhere in Kubernetes manifests.**

