# Runbook — Data stale triage

## Safety posture

- Keep execution disabled while diagnosing data freshness.
- Prefer read-only checks first; restart only the minimal data-ingest component if approved.

## When to use

- Alert: **data stale** / **marketdata stale**
- Freshness metric (e.g., `heartbeat_age_seconds`, `last_tick_age_seconds`) rises and stays above threshold
- Downstream strategies enter degraded behavior due to missing/old inputs

## Identify the stale producer (fast)

```bash
export NAMESPACE="trading-floor"

# Pods and their age/restarts
kubectl -n "$NAMESPACE" get pods -o wide

# If you know the app label (example: marketdata service)
kubectl -n "$NAMESPACE" get pods -l app=marketdata-mcp-server -o wide
```

### What “good” looks like

The producer is `Running` and `Ready`, with stable restarts:

```text
NAME                                   READY   STATUS    RESTARTS   AGE
marketdata-mcp-server-7f8c9d5f6-2m7xk   1/1     Running   0          3h
```

## Check health and freshness endpoints (in-cluster)

Use in-pod checks (no external network dependencies):

```bash
export POD="$(kubectl -n "$NAMESPACE" get pods -l app=marketdata-mcp-server -o jsonpath='{.items[0].metadata.name}')"

# /ops/status (example)
kubectl -n "$NAMESPACE" exec "$POD" -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/ops/status', timeout=5).read().decode())"

# /metrics (trim output; still useful to confirm key counters move)
kubectl -n "$NAMESPACE" exec "$POD" -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/metrics', timeout=5).read().decode()[:1200])"
```

### What “good” looks like

`/ops/status` returns `ok: true` and a recent timestamp/age:

```json
{"ok": true, "last_tick_epoch_seconds": 1767794832, "last_tick_age_seconds": 2}
```

Metrics show freshness improving and counters increasing over time:

```text
heartbeat_age_seconds 2
marketdata_ticks_total 123456
```

## Logs: confirm whether upstream is disconnected vs. internal slowdown

```bash
kubectl -n "$NAMESPACE" logs "$POD" --tail=200
```

What “good” looks like:
- periodic “connected / subscribed” messages (if applicable)
- no repeating auth failures, reconnect loops, or timeouts

## Cluster-level signals that commonly cause “stale”

### 1) DNS / network to upstream (quick connectivity check)

Create a temporary debug pod (auto-deletes on exit):

```bash
export SERVICE="marketdata-mcp-server"
kubectl -n "$NAMESPACE" run net-debug --rm -i --restart=Never --image=nicolaka/netshoot:latest -- \
  sh -lc 'set -e; echo "DNS (cluster):"; nslookup kubernetes.default.svc.cluster.local >/dev/null && echo "ok"; echo "HTTP (service):"; curl -fsS "http://'"$SERVICE"'/healthz" >/dev/null && echo "ok"'
```

What “good” looks like:

```text
DNS (cluster):
ok
HTTP (service):
ok
```

### 2) Resource pressure / throttling

```bash
kubectl -n "$NAMESPACE" describe pod "$POD"
kubectl get nodes
```

What “good” looks like:
- no repeating `OOMKilled`
- no node `NotReady`
- no warning events about evictions / pressure

## Safe remediation (requires approval)

### Restart only the producer workload (Deployment)

This is often safe for marketdata collectors and does **not** enable execution by itself.

```bash
export DEPLOY="marketdata-mcp-server"
kubectl -n "$NAMESPACE" rollout restart deploy/"$DEPLOY"
kubectl -n "$NAMESPACE" rollout status deploy/"$DEPLOY" --timeout=10m
kubectl -n "$NAMESPACE" get pods -l app=marketdata-mcp-server -o wide
```

### What “good” looks like after restart

```text
deployment "marketdata-mcp-server" successfully rolled out
```

and `last_tick_age_seconds` returns to a low steady value (e.g., < 5s).

## Done criteria

- Freshness age metrics return below threshold and remain stable
- Counters like `*_ticks_total`/`*_events_total` increase over time
- No repeating upstream auth/network errors in logs

