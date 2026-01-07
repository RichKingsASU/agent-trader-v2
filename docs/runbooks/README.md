# Production Runbooks (Institutional)

This folder contains **copy/paste-ready** runbooks for common production incidents and operational procedures.

## Conventions

- **Safety first**: prefer *read-only* diagnostics; any change is explicitly called out.
- **Use variables**: set these once per terminal session.

```bash
# Kubernetes
export NAMESPACE="trading-floor"
kubectl config current-context

# GCP (Cloud Build)
export PROJECT_ID="<your-gcp-project-id>"
gcloud config set project "$PROJECT_ID"
gcloud config get-value project
```

## Index

- `crashloopbackoff-triage.md` — Pods in `CrashLoopBackOff`: fast triage + what “good” looks like
- `cloud-build-failure-triage.md` — Cloud Build failures: identify failing step, logs, common root causes
- `data-stale-triage.md` — Data/marketdata stale: heartbeat and freshness checks, safe restart options
- `k8s-rollout-procedure-observe-only.md` — **Observe-only** rollout monitoring procedure (no cluster changes)

## Evidence to capture (always)

When you open an incident, capture these early:

```bash
date -u
kubectl -n "$NAMESPACE" get pods -o wide
kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -n 50
```

For Cloud Build incidents, capture:

```bash
gcloud builds list --limit=10 --format="table(id,status,createTime,source.repoSource.repoName,logUrl)"
```

