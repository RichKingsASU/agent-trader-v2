# Runbook — CrashLoopBackOff triage

## Safety posture

- Keep execution disabled (do not change kill switch / execution flags during triage).
- Prefer **rollback to last-known-good** over “hotfixing in prod”.
- Collect evidence before restarting pods.

## When to use

- Pod status shows `CrashLoopBackOff`
- Restart count is increasing
- Readiness never becomes `Ready`

## Fast triage (copy/paste)

```bash
export NAMESPACE="trading-floor"

# 1) Identify crashlooping pods
kubectl -n "$NAMESPACE" get pods -o wide

# 2) Pick a pod name and capture the container state + last termination reason
export POD="<pod-name>"
kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.status.containerStatuses[*].name}{"\n"}{.status.containerStatuses[*].state}{"\n"}{.status.containerStatuses[*].lastState}{"\n"}'

# 3) Describe for events (probe failures, image issues, mount errors)
kubectl -n "$NAMESPACE" describe pod "$POD"

# 4) Logs (current + previous crash)
kubectl -n "$NAMESPACE" logs "$POD" --tail=200
kubectl -n "$NAMESPACE" logs "$POD" --previous --tail=200
```

### What “good” looks like

`kubectl -n "$NAMESPACE" get pods -o wide` shows **Ready** and stable restarts:

```text
NAME                                   READY   STATUS    RESTARTS   AGE   IP            NODE
marketdata-mcp-server-7f8c9d5f6-2m7xk   1/1     Running   0          22m   10.48.2.17    gke-prod-pool-1-abc
strategy-engine-6f78c9c7b9-8qv2n        1/1     Running   0          22m   10.48.1.103   gke-prod-pool-1-def
```

CrashLoopBackOff typically looks like:

```text
NAME                                   READY   STATUS             RESTARTS   AGE
strategy-engine-6f78c9c7b9-8qv2n        0/1     CrashLoopBackOff   7          11m
```

In `kubectl describe pod "$POD"`, a common crashloop event looks like:

```text
Warning  BackOff  2m3s (x12 over 10m)  kubelet  Back-off restarting failed container
```

## Narrow down root cause

### 1) Is it configuration/secret/mount related?

Look for these in `kubectl describe pod` events:
- `CreateContainerConfigError`
- `Error: secret "<name>" not found`
- `MountVolume.SetUp failed`

Confirm which ConfigMaps/Secrets are referenced (read-only):

```bash
kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.spec.volumes[*].configMap.name}{"\n"}{.spec.volumes[*].secret.secretName}{"\n"}'
```

What “good” looks like: the referenced objects exist.

```bash
kubectl -n "$NAMESPACE" get secret/<secret-name>
kubectl -n "$NAMESPACE" get configmap/<configmap-name>
```

Expected:

```text
NAME          TYPE     DATA   AGE
<secret-name> Opaque   5      120d
```

### 2) Is it an image/entrypoint mismatch?

```bash
kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.spec.containers[*].image}{"\n"}'
kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.spec.containers[*].command}{"\n"}{.spec.containers[*].args}{"\n"}'
```

What “good” looks like: image points to the expected registry/tag and container starts without immediate exit.

### 3) Is it a probe issue (app runs, but gets killed)?

```bash
kubectl -n "$NAMESPACE" get pod "$POD" -o jsonpath='{.spec.containers[*].livenessProbe}{"\n"}{.spec.containers[*].readinessProbe}{"\n"}'
kubectl -n "$NAMESPACE" describe pod "$POD"
```

What “good” looks like in events: no repeating `Liveness probe failed` / `Readiness probe failed`.

## Safe remediation options (requires change approval)

These actions **change** the system. Use only if your on-call policy allows it.

### A) Restart the owning controller (Deployment)

```bash
export DEPLOY="<deployment-name>"
kubectl -n "$NAMESPACE" rollout restart deploy/"$DEPLOY"
kubectl -n "$NAMESPACE" rollout status deploy/"$DEPLOY" --timeout=10m
```

### B) Roll back Deployment to prior ReplicaSet (if a bad image/config was just rolled out)

```bash
export DEPLOY="<deployment-name>"
kubectl -n "$NAMESPACE" rollout history deploy/"$DEPLOY"
kubectl -n "$NAMESPACE" rollout undo deploy/"$DEPLOY"
kubectl -n "$NAMESPACE" rollout status deploy/"$DEPLOY" --timeout=10m
```

## Done criteria

- Pod(s) are `Running` and `Ready` for **10+ minutes**
- Restart count stops increasing
- No new Warning events for the workload

