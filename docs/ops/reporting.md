## AgentTrader v2 — “Where are my workloads?” deployment report

This repo includes a deterministic deployment report generator for the AgentTrader v2 “trading floor”.

It answers, in one page:
- **What is deployed** (Deployments / StatefulSets / Jobs / Services)
- **Where** (context + namespace)
- **With what image** (full Artifact Registry image + tag)
- **Is it healthy** (readiness + lightweight HTTP probes when possible)
- **Is it allowed to run** (based on `KILL_SWITCH` / `AGENT_MODE` presence and values)

This is a **read-only** audit tool. It does **not** enable trading and does **not** modify cluster state.

### How to run

Local (uses your current `kubectl` context):

```bash
chmod +x ./scripts/report_v2_deploy.sh
./scripts/report_v2_deploy.sh
```

Explicit namespace / context:

```bash
./scripts/report_v2_deploy.sh --namespace trading-floor
./scripts/report_v2_deploy.sh --context <your-context-name> --namespace trading-floor
```

Skip health sampling (no port-forward):

```bash
./scripts/report_v2_deploy.sh --skip-health
```

### Outputs

The script writes:
- `audit_artifacts/deploy_report.md` (primary)
- `audit_artifacts/deploy_report.json` (secondary)

### Interpretation: ok vs degraded vs halted

- **ok**: replicas are ready *and* at least one health probe (`/healthz` or `/health`) succeeds when sampling is available.
- **degraded**: replicas are not fully ready, pods show crash/image-pull symptoms, or health probes fail.
- **halted / not allowed**: `KILL_SWITCH=true` (or similar truthy value) **or** `AGENT_MODE` is set to `off/halted/paused/disabled`.

> Note: `KILL_SWITCH` is optional. If it’s absent, the report treats the workload as **allowed** unless `AGENT_MODE` explicitly disables it.

### Useful kubectl queries

List AgentTrader v2 workloads by standard labels:

```bash
kubectl -n trading-floor get deploy,statefulset,job,svc -l app.kubernetes.io/part-of=agent-trader-v2
```

Show pods for the v2 trading floor:

```bash
kubectl -n trading-floor get pods -l app.kubernetes.io/part-of=agent-trader-v2
```

### Label contract (what the report relies on)

All AgentTrader v2 Kubernetes manifests should include these labels on workloads and services:
- `app.kubernetes.io/name=agenttrader`
- `app.kubernetes.io/part-of=agent-trader-v2`
- `app.kubernetes.io/component=<marketdata|strategy|ops|ingest|mcp>`
- `app.kubernetes.io/instance=<workload name>`

