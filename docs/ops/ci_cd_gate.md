# CI/CD Institutional Gate (AgentTrader v2)

This repo uses a **fail-closed CI gate** to ensure merges to `main` produce an auditable result **without accidentally deploying unsafe configs**.

## What CI checks

- **Python sanity**
  - `python -m compileall backend/`
  - `pytest` (runs a lightweight smoke suite if tests are present)
- **Kubernetes safety lint** (required)
  - Fails if any `k8s/` manifest contains **`:latest`**
  - Fails if any `k8s/` manifest contains **`AGENT_MODE=EXECUTE`** (inline or YAML env form)
  - Fails if workload manifests are missing:
    - required label: `app.kubernetes.io/part-of: agent-trader-v2`
    - required identity env vars: `REPO_ID`, `AGENT_NAME`, `AGENT_ROLE`, `AGENT_MODE`
- **Dependency pinning enforcement** (lightweight)
  - Fails if any `requirements*.txt` contains an **unpinned** dependency (not `==` and not a direct reference `@`), unless allowlisted in `.ci/requirements_allowlist.txt`.
- **Kubernetes dry-run validation**
  - If cluster creds are available: `kubectl apply --server-side --dry-run=server -f k8s/`
  - Otherwise: `kubectl apply --dry-run=client -f k8s/`
- **Deploy report artifact (best-effort)**
  - Always generates:
    - `audit_artifacts/deploy_report.md`
    - `audit_artifacts/deploy_report.json`
  - If the cluster is unreachable, the report explains why (it must still be produced).

## Run locally

From repo root:

```bash
./scripts/ci_safety_lint.sh
python3 ./scripts/ci_requirements_pinning_check.py
python3 -m compileall backend/
python3 -m pytest -q \
  tests/test_timeutils.py \
  tests/test_agent_state_machine.py \
  tests/test_risk_manager.py \
  tests/test_watchdog.py
kubectl apply --dry-run=client -f k8s/
python3 ./scripts/report_v2_deploy.py
```

To run the **full test suite** (may be slower and may surface pre-existing failures), run:

```bash
python3 -m pytest
```

## Artifacts

CI uploads the `audit_artifacts/` folder:
- `audit_artifacts/deploy_report.md`
- `audit_artifacts/deploy_report.json`

## Interpreting failures

- **Safety lint failure**
  - Output includes **file + line** context for forbidden patterns, or a file/anchor line for missing required labels/env vars.
- **Requirements pinning failure**
  - Output includes **file + line** for each unpinned requirement.
  - To temporarily allow an entry (while migrating to full pinning), add either:
    - the base package name, or
    - the exact requirement line
    to `.ci/requirements_allowlist.txt`.

