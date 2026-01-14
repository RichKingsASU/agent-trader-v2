# Repository structure (canonical map)

This repo is intentionally a **Python-first** monorepo with a small number of buildable/deployable “surfaces”.
The goal of this document is to make the **single source of truth** for each surface explicit and to prevent
legacy/duplicate trees from silently reappearing.

## Proposed scaffold map (canonical)

### Runtime services (Python)

- **`backend/`**: canonical Python services and libraries.
  - **Mission Control (read-only ops API)**: `backend/mission_control/`
  - **Execution Engine (hard-gated)**:
    - API service entrypoint: `backend/services/execution_service/app.py`
    - Core engine implementation: `backend/execution/`
  - **Execution Agent (stub / OBSERVE-only)**: `backend/execution_agent/`

### UI (TypeScript / React)

- **`frontend/ops-ui/`**: **canonical Ops UI** (Vite SPA).
  - Build output: `frontend/ops-ui/dist`
  - Firebase Hosting config: `firebase.json` (`public: frontend/ops-ui/dist`)
  - K8s deployment: `k8s/ops-ui/`

### Configuration (checked in, no secrets)

- **`configs/`**: canonical runtime configuration (YAML) consumed by services.
  - Example: `configs/agents/agents.yaml` (Mission Control default via `AGENTS_CONFIG_PATH`)
- **`config/`**: small, repo-local “preflight” configuration used by developer/CI tooling.
  - Example: `config/preflight.yaml` (captured by `scripts/capture_config_snapshot.sh`)

### Operations / infra / automation

- **`k8s/`**: Kubernetes manifests (pinned images; no `:latest`).
- **`infra/`**: Cloud Build / Cloud Run / deployment scaffolding.
- **`ops/`**: production locks, runbooks, ops policies, and operational documentation.
- **`scripts/`**: deterministic automation scripts (no secrets).
- **`docs/`**: design docs, runbooks, contracts, and reference material.

## Legacy / duplicate directories (status)

- **`apps/ops-dashboard/`**: legacy/duplicate Ops UI tree. Removed because it was not referenced by any build/deploy paths
  and was not buildable as a standalone Node project.

## Single source of truth (confirmed)

- **Ops UI**: `frontend/ops-ui/`
- **Mission Control**: `backend/mission_control/`
- **Execution Engine**: `backend/services/execution_service/` (API) + `backend/execution/` (core)

