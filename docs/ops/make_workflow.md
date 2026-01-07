# Trading Floor Makefile Workflow (AgentTrader v2)

This repo uses a single entrypoint (`Makefile` at repo root) to reduce scattered commands and make deployments **deterministic, repeatable, and safe**.

## Day 0 setup (local workstation)

- **Install required tools**
  - **git**
  - **python3**
  - **kubectl** (for cluster workflows)
  - **docker** (optional; only needed for `make build`)
  - **gcloud** (optional; used by some guardrails for context/image checks)

- **Confirm you can run repo scripts**

```bash
bash --version
python3 --version
```

- **Confirm cluster access (if using k8s targets)**

```bash
kubectl version --client
kubectl config get-contexts
kubectl config current-context
kubectl get ns
```

- **Optional: set defaults**
  - Prefer passing vars per command for determinism, but you can export them:

```bash
export NAMESPACE=trading-floor
export CONTEXT="gke_<project>_<location>_<cluster>"   # optional but recommended
export MISSION_CONTROL_URL="http://agenttrader-mission-control"
```

## Common flows

### Safe deploy (recommended)

```bash
make guard && make deploy && make report
```

Notes:
- `make guard` runs `scripts/predeploy_guard.sh` and **fails fast** on unsafe manifests (e.g. forbidden `AGENT_MODE=EXECUTE`, `:latest` tags).
- `make deploy` prefers `scripts/deploy_v2.sh` (deterministic rollout + report), otherwise falls back to `kubectl apply`.
- `make report` writes audit-friendly artifacts under `audit_artifacts/`.

### Pre-market readiness gate (fail-closed)

```bash
make readiness NAMESPACE=trading-floor
```

This runs `scripts/readiness_check.sh` and writes:
- `audit_artifacts/readiness_report.md`
- `audit_artifacts/readiness_report.json`

### Debugging: status + logs

```bash
make status NAMESPACE=trading-floor
make logs NAMESPACE=trading-floor AGENT=strategy-engine
```

### Scale a workload (ops action)

```bash
make scale NAMESPACE=trading-floor AGENT=strategy-engine REPLICAS=2
```

### Port-forward a service (local inspection)

```bash
make port-forward NAMESPACE=trading-floor AGENT=agenttrader-mission-control PORT=8080:8080
```

## Troubleshooting

### Wrong context / namespace

Symptoms:
- Guard fails with context mismatch
- `make status` says namespace not found / cluster unreachable

Fix:

```bash
kubectl config get-contexts
kubectl config use-context <correct-context>
kubectl get ns
```

Or run commands explicitly with deterministic overrides:

```bash
make status CONTEXT=<correct-context> NAMESPACE=trading-floor
make guard  CONTEXT=<correct-context> NAMESPACE=trading-floor
```

### `kubectl` not installed

K8S targets (`deploy`, `status`, `logs`, `scale`, `port-forward`, `readiness`) require `kubectl`.

### Mission Control `/ops/status` not reachable

`make status` probes `MISSION_CONTROL_URL/ops/status` **best-effort**.

- If `curl` is missing: the probe is skipped.
- If the URL is not resolvable from your network: set `MISSION_CONTROL_URL` to something reachable (e.g. after a `make port-forward`).

## Target index

Run:

```bash
make help
```

