## CI ownership: GitHub Actions vs Cloud Build

This repo intentionally splits CI responsibilities to keep pull requests fast and safe, while ensuring **all container builds/pushes** happen in a single, controlled system.

### GitHub Actions (lint-only / merge gates)

GitHub Actions is used for **read-only validation** on `pull_request` (and a lightweight check on `main`), with **no cloud credentials** and **no cloud tooling**.

- **Allowed**
  - **YAML validation** (syntax parsing only; no schema validation requiring clusters)
  - **Safety guard (read-only)** via `scripts/ci_safety_guard.sh`
  - **Python import smoke checks** via `scripts/smoke_check_imports.py`
  - **Static repo blockers** (secret markers, banned references, etc.)
  - **Cloud Build config linting** (e.g. `scripts/validate_cloudbuild_configs.sh`, `scripts/validate_ci_layout.sh`)

- **Not allowed**
  - **Docker builds** (no `docker build`, no `buildx`, no image push)
  - **Cloud calls** (no `gcloud`, no `kubectl`, no deploy actions)
  - **Any step requiring cloud credentials**

If a PR needs a container image to be built/tested, that work belongs in Cloud Build.

### Cloud Build (build / push / deploy)

Cloud Build is the **only** system responsible for:

- **Building container images**
- **Running container/image gates** (e.g. `scripts/ci_import_gate.sh` against a built image)
- **Pushing images to the registry**
- **Deploying** (where applicable) using cloud tooling (`gcloud`, `kubectl`, etc.)

This keeps image provenance consistent and prevents GitHub Actions PR workflows from becoming an implicit deployment pipeline.

