# Runbook — Kubernetes rollout procedure (OBSERVE-only)

## Safety posture

- This procedure is **observe-only**: it does **not** change cluster state.
- Use it to monitor a rollout initiated by CI/CD or an authorized change.
- If health degrades, stop and escalate to the change owner for rollback decisions.

## Prereqs

```bash
export NAMESPACE="trading-floor"
kubectl config current-context
```

## 0) Identify the workload being rolled out

Set one target (Deployment or StatefulSet):

```bash
export KIND="deploy"            # or: sts
export NAME="<workload-name>"   # e.g. marketdata-mcp-server, strategy-engine, gamma-strategy
```

Confirm it exists and capture baseline:

```bash
kubectl -n "$NAMESPACE" get "$KIND/$NAME" -o wide
kubectl -n "$NAMESPACE" get "$KIND/$NAME" -o jsonpath='{.metadata.generation}{"\n"}{.status.observedGeneration}{"\n"}'
```

### What “good” looks like

Observed generation catches up quickly (same numbers):

```text
12
12
```

## 1) Watch rollout status (read-only)

```bash
kubectl -n "$NAMESPACE" rollout status "$KIND/$NAME" --timeout=15m
```

### What “good” looks like

```text
deployment "strategy-engine" successfully rolled out
```

or (StatefulSet):

```text
statefulset rolling update complete 3 pods at revision gamma-strategy-7b7d9c5c9c
```

## 2) Verify replicas and readiness

```bash
kubectl -n "$NAMESPACE" get "$KIND/$NAME" -o wide
```

Get the workload selector labels (then use them to list pods):

```bash
kubectl -n "$NAMESPACE" get "$KIND/$NAME" -o jsonpath='{.spec.selector.matchLabels}{"\n"}'

# Template (fill in key/value pairs from the previous command):
kubectl -n "$NAMESPACE" get pods -l key=value,otherkey=othervalue -o wide
```

If you already know there is an `app` label, this also works:

```bash
kubectl -n "$NAMESPACE" get pods -l app="$NAME" -o wide
```

### What “good” looks like

Pods are `Running` and `Ready`, with restarts not spiking:

```text
NAME                                   READY   STATUS    RESTARTS   AGE
strategy-engine-6f78c9c7b9-8qv2n        1/1     Running   0          4m
strategy-engine-6f78c9c7b9-q5jz9        1/1     Running   0          4m
```

## 3) Confirm the new image is running

```bash
# Desired image(s) in the template
kubectl -n "$NAMESPACE" get "$KIND/$NAME" -o jsonpath='{.spec.template.spec.containers[*].image}{"\n"}'

# Images actually running in pods
kubectl -n "$NAMESPACE" get pods -l app="$NAME" -o jsonpath='{range .items[*]}{@.metadata.name}{"\t"}{@.spec.containers[*].image}{"\n"}{end}'
```

### What “good” looks like

All pods show the same expected tag/digest:

```text
strategy-engine-6f78c9c7b9-8qv2n   us-docker.pkg.dev/<project>/<repo>/strategy-engine:<tag>
strategy-engine-6f78c9c7b9-q5jz9   us-docker.pkg.dev/<project>/<repo>/strategy-engine:<tag>
```

## 4) Check events for early warning signs

```bash
kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -n 50
kubectl -n "$NAMESPACE" describe "$KIND/$NAME"
```

### What “good” looks like

No repeating warnings like:
- `FailedScheduling`
- `Back-off restarting failed container`
- `Readiness probe failed`
- `ImagePullBackOff`

## 5) Validate Service routing (endpoints ready)

If there is a Service for the workload:

```bash
kubectl -n "$NAMESPACE" get svc
```

Confirm the Service has ready backends (observe-only):

```bash
export SERVICE="<service-name>"    # e.g. marketdata-mcp-server
kubectl -n "$NAMESPACE" get svc "$SERVICE" -o wide
kubectl -n "$NAMESPACE" get endpoints "$SERVICE" -o wide
```

Optional (still observe-only): if the workload container already includes `curl` or `python`, exec into an existing pod to query its local health endpoint.

```bash
export POD="<pod-name>"
kubectl -n "$NAMESPACE" exec "$POD" -- python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).read().decode())"
```

### What “good” looks like

Endpoints show at least one ready address:

```text
NAME                 ENDPOINTS                         AGE
marketdata-mcp-server 10.48.2.17:8080,10.48.1.103:8080  120d
```

## 6) If rollout stalls, capture evidence (still observe-only)

```bash
kubectl -n "$NAMESPACE" rollout status "$KIND/$NAME" --timeout=2m
kubectl -n "$NAMESPACE" get pods -o wide
kubectl -n "$NAMESPACE" describe pods
kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -n 100
```

Stall patterns to look for:
- old pods not terminating (PDB / finalizers / stuck node)
- new pods not becoming Ready (probe failures / config / dependency)
- image pulls failing (registry/credentials)

## Done criteria

- `kubectl rollout status` reports **successfully rolled out**
- All pods are `Running` and `Ready`
- Health endpoint returns success from inside the cluster
- No repeating warning events for at least **10 minutes**

