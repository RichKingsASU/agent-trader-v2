## Runbook — Strategy engine halted/unhealthy

### Symptoms

- Alert fires: **“Strategy engine halted/unhealthy (critical)”**
- `strategy_cycles_total` stops increasing
- `/ops/status` may show old `last_cycle_at` / high `last_cycle_age_seconds`

### Immediate checks

```bash
NAMESPACE=trading-floor

# gamma
kubectl -n "$NAMESPACE" get pods -l strategy=gamma -o wide
kubectl -n "$NAMESPACE" logs -l strategy=gamma --tail=200

POD_GAMMA="$(kubectl -n "$NAMESPACE" get pods -l strategy=gamma -o jsonpath='{.items[0].metadata.name}')"
kubectl -n "$NAMESPACE" exec "$POD_GAMMA" -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/ops/status').read().decode())"
kubectl -n "$NAMESPACE" exec "$POD_GAMMA" -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/metrics').read().decode()[:800])"

# whale (if deployed)
kubectl -n "$NAMESPACE" get pods -l strategy=whale -o wide
kubectl -n "$NAMESPACE" logs -l strategy=whale --tail=200
```

### Likely causes

- Crashloop (unhandled exception, missing env/config, dependency failure)
- Downstream dependency failures (DB, Firestore, marketdata)
- Kill switch enabled (should prevent execution; may be intentional)
- Resource starvation (OOMKills / CPU throttling)

### Safe remediation steps (safety posture)

- **Confirm kill switch state**:
  - If the kill switch is enabled intentionally, the system is in a safe posture; focus on restoring inputs and only then consider clearing it via your standard ops process.

- **Restart the strategy pod** (safe; does not enable execution by itself):

```bash
NAMESPACE=trading-floor
kubectl -n "$NAMESPACE" rollout restart statefulset/gamma-strategy
kubectl -n "$NAMESPACE" rollout status statefulset/gamma-strategy --timeout=5m
```

- **If it’s a config/env regression**:
  - roll back the workload image tag to the last known-good build using your deployment pipeline

### Verification

- `/ops/status` shows recent `last_cycle_at`
- `strategy_cycles_total` increases over time
- `strategy_cycles_skipped_total` does not spike

