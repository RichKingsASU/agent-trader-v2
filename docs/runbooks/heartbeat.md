# Heartbeats (OBSERVE-mode “Are We Alive?”)

This runbook covers how to verify **in-cluster liveness/readiness** and a **lightweight 1-minute ops heartbeat** for OBSERVE-mode services in the `trading-floor` namespace.

## What exists

- **HTTP probes**
  - `marketdata-mcp-server`: `GET /healthz` (liveness), `GET /readyz` (readiness)
  - `strategy-engine` / `strategy-runtime` workloads (gamma/whale + strategy-engine deployment): `GET /healthz` (liveness), `GET /readyz` (readiness)
- **Ops heartbeat CronJob**
  - CronJob: `ops-heartbeat-writer` (runs every minute)
  - ConfigMap target: `agenttrader-heartbeat-ops-cron` with `.data.last_seen` updated once per minute

## Quick checks

### Check Kubernetes probe status

```bash
kubectl -n trading-floor get pods
kubectl -n trading-floor describe pod -l app=marketdata-mcp-server | sed -n '/Containers:/,/Conditions:/p'
kubectl -n trading-floor describe pod -l app=strategy-engine | sed -n '/Containers:/,/Conditions:/p'
```

### Hit the endpoints from inside the cluster

```bash
kubectl -n trading-floor run -it --rm tmp-curl --image=curlimages/curl:latest --restart=Never -- \
  sh -lc 'set -e; echo "marketdata"; curl -fsS http://marketdata-mcp-server/healthz; echo; curl -fsS http://marketdata-mcp-server/readyz; echo; echo "strategy"; curl -fsS http://agenttrader-strategy-engine/healthz; echo; curl -fsS http://agenttrader-strategy-engine/readyz; echo'
```

## Ops heartbeat CronJob checks

### Confirm the CronJob is running every minute

```bash
kubectl -n trading-floor get cronjob ops-heartbeat-writer
kubectl -n trading-floor get jobs --sort-by=.metadata.creationTimestamp | tail -n 10
```

### Verify the heartbeat timestamp in the ConfigMap

```bash
kubectl -n trading-floor get configmap agenttrader-heartbeat-ops-cron -o jsonpath='{.data.last_seen}{"\n"}'
```

### Inspect CronJob logs

```bash
kubectl -n trading-floor logs job -l app.kubernetes.io/name=ops-heartbeat-writer --tail=50
```

## Notes / expectations

- **/healthz** is intentionally lightweight: it should only prove the process is up (no external dependency gating).
- **/readyz** indicates the service has initialized its in-process dependencies and can serve traffic.
- This heartbeat mechanism is **non-trading** and does **not** enable execution.
