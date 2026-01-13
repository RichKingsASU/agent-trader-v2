## Rollback procedures (production-safe, fail-closed)

This document defines **rollback** procedures for AgentTrader v2. “Rollback” means returning to a **known-good** version/config while preserving the default **non-executing** safety posture.

### Absolute safety rules

- **Do not enable trading execution** as part of rollback.
- **Keep the kill switch HALTED**: `EXECUTION_HALTED=1` (see `docs/KILL_SWITCH.md`).
- Prefer **deterministic restore** (LKG / pinned digests / prior revisions) over “hotfix forward”.

---

## A) Kubernetes rollback (trading floor) — preferred: LKG restore

Authoritative safety posture and lock: `ops/PRODUCTION_LOCK.md`  
Authoritative LKG details: `ops/lkg/lkg_readme.md`

### Rollback to Last Known Good (LKG)

This is the default rollback for the Kubernetes “trading floor” deployment.

```bash
# Restores the namespace resources and workloads pinned to digests
# and enforces EXECUTION_HALTED="1" as part of restore.
./scripts/restore_lkg.sh trading-floor
```

### Verify after rollback

```bash
kubectl -n trading-floor get pods -o wide
kubectl -n trading-floor get deploy,sts
kubectl -n trading-floor get configmap agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'
```

Expected:

- Workloads are Ready/Available (no CrashLoopBackOff / ImagePullBackOff).
- Kill switch prints **`1`**.

---

## B) Cloud Run rollback (GCP)

Authoritative deployment path: `docs/DEPLOY_GCP.md`

### Cloud Run Services (traffic rollback to a prior revision)

1) Identify prior revisions:

```bash
gcloud run revisions list --service "market-ingest" --region "${REGION}" --project "${PROJECT_ID}"
gcloud run revisions list --service "execution-engine" --region "${REGION}" --project "${PROJECT_ID}"
```

2) Shift traffic back to a known-good revision:

```bash
# Example: route 100% traffic to a prior revision
gcloud run services update-traffic "market-ingest" \
  --to-revisions "market-ingest-00042-abc=100" \
  --region "${REGION}" \
  --project "${PROJECT_ID}"
```

3) Verify health contracts:

- Market ingest: `GET /health` and freshness gate `GET /healthz` (see `docs/MARKETDATA_HEALTH_CONTRACT.md`)
- Execution engine: `GET /health` (and keep execution halted)

### Cloud Run Jobs (redeploy a known-good digest)

Cloud Run Jobs do not use “traffic splitting”. Rollback means redeploying the job to a known-good image digest.

1) Determine the known-good image (prefer: pinned digest from your release record):

- From your change control / release evidence (preferred), or
- From Artifact Registry inventory snapshots (if captured), or
- From previous Cloud Build artifacts.

2) Redeploy the job with the known-good image:

```bash
gcloud run jobs deploy "${JOB_NAME}" \
  --image "${IMAGE_DIGEST}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --env-vars-file "PATH_TO_ENV_VARS_FILE"
```

3) Execute and verify:

```bash
gcloud run jobs execute "${JOB_NAME}" --region "${REGION}" --project "${PROJECT_ID}" --wait
```

---

## C) Ops Dashboard (Firebase Hosting) rollback

Authoritative deploy doc: `docs/ops/firebase_ops_dashboard_deploy.md`

Preferred rollback options (choose the most deterministic available in your environment):

- **Redeploy the last-known-good commit** for the Ops UI build (fast and auditable).
- Use the **Firebase Hosting release history** in the Firebase Console to roll back to a prior release (when available in your org’s process).

Safety note:

- Rollback should not add new runtime controls that mutate production state; Ops UI is intended to remain **read-only** under the production lock (`ops/PRODUCTION_LOCK.md`).

