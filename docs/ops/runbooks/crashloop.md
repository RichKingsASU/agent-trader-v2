## Runbook — CrashLoop / frequent restarts

### Symptoms

- Alert fires: **“CrashLoop / frequent restarts (critical)”**
- Pods show `CrashLoopBackOff` or high restart count
- Logs show repeated startup messages and exits

### Immediate checks

```bash
NAMESPACE=trading-floor

kubectl -n "$NAMESPACE" get pods -o wide
kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -n 50

# Describe a crashing pod (replace POD)
POD="<pod-name>"
kubectl -n "$NAMESPACE" describe pod "$POD"

# See previous container logs (often the real failure)
kubectl -n "$NAMESPACE" logs "$POD" --previous --tail=200 || true
kubectl -n "$NAMESPACE" logs "$POD" --tail=200
```

### Likely causes

- Missing required env var / secret / configmap key
- Bad image / dependency import failure
- Permission issues (service account / IAM)
- OOMKilled due to memory limits
- Bind error (port already in use) / bad healthcheck

### Safe remediation steps

- **Fix config first** (secrets/configmaps), then restart:

```bash
kubectl -n "$NAMESPACE" rollout restart deploy/marketdata-mcp-server || true
kubectl -n "$NAMESPACE" rollout restart statefulset/gamma-strategy || true
kubectl -n "$NAMESPACE" rollout restart statefulset/whale-strategy || true
```

- **If it started immediately after a deploy**: roll back to last known-good image tag using your deployment pipeline.

- **If OOMKilled**: increase memory request/limit or reduce workload; verify via:

```bash
kubectl -n "$NAMESPACE" describe pod "$POD" | sed -n '/Last State:/,/Ready:/p'
```

### Verification

- Pod reaches `Running` and stays stable (no restarts)
- `/health` and `/ops/status` respond inside the container
- Dashboards show restart delta returning to zero

