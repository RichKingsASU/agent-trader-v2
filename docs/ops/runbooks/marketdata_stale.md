## Runbook — Marketdata stale

### Symptoms

- Alert fires: **“Marketdata stale (warning)”**
- `heartbeat_age_seconds` rises steadily and stays above threshold
- Strategy components may move into DEGRADED behavior (or stop proposing actions)

### Immediate checks

```bash
NAMESPACE=trading-floor

kubectl -n "$NAMESPACE" get pods -l app=marketdata-mcp-server -o wide
kubectl -n "$NAMESPACE" logs -l app=marketdata-mcp-server --tail=200

# In-pod endpoint checks (no curl required)
POD="$(kubectl -n "$NAMESPACE" get pods -l app=marketdata-mcp-server -o jsonpath='{.items[0].metadata.name}')"
kubectl -n "$NAMESPACE" exec "$POD" -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/ops/status').read().decode())"
kubectl -n "$NAMESPACE" exec "$POD" -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/metrics').read().decode()[:800])"
```

### Likely causes

- Alpaca stream disconnected / auth failures / upstream outage
- Networking/DNS issues in cluster
- DB errors causing handler slowdown (writes blocking)
- Resource pressure (CPU throttling / memory pressure)

### Safe remediation steps (non-execution)

- **Restart the marketdata pod** (safe; does not enable execution):

```bash
NAMESPACE=trading-floor
kubectl -n "$NAMESPACE" rollout restart deploy/marketdata-mcp-server
kubectl -n "$NAMESPACE" rollout status deploy/marketdata-mcp-server --timeout=5m
```

- **Check credentials/config** (do not print secrets):
  - ensure required env vars exist (API keys via secret, DB URL, etc.)
  - confirm any kill-switch config is present (it should *not* affect marketdata collection, but may indicate broader incident)

### Verification

- `heartbeat_age_seconds` returns to a low steady value
- `marketdata_ticks_total` increases over time
- `/health`, `/ops/status`, and `/metrics` respond from inside the pod

