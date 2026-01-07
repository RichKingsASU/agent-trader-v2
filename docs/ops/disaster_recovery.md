## AgentTrader v2 — Disaster Recovery & Backups (Cluster + Artifacts + LKG)

This runbook provides a **scripted, reproducible** restore path for the v2 “trading floor” after cluster breakage, bad deploys, accidental deletion, or config drift.

### Safety invariant (absolute rule)

- **Trading execution must remain disabled** during DR operations.
- The DR flow enforces the kill switch:
  - `ConfigMap/agenttrader-kill-switch` → `EXECUTION_HALTED="1"`

### RTO / RPO targets (placeholders)

- **RTO (restore time objective)**: 30–60 minutes for “restore to LKG” on an existing cluster context.
- **RPO (restore point objective)**:
  - Cluster state: last **daily** snapshot (24h)
  - Artifact inventory: last manual/scheduled snapshot
  - LKG: last captured point (manual or scheduled)

### What to back up (and where)

- **LKG marker**: `ops/lkg/`
  - `lkg_manifest.yaml`: apply-able manifest pinned to image digests (no tags)
  - `lkg_metadata.json`: provenance + component digest inventory + safety posture

- **Cluster snapshot (GitOps-style)**:
  - `audit_artifacts/cluster_backup/<timestamp>/`
  - Exports: `deploy`, `sts`, `svc`, `cm`, `sa`, `role`, `rolebinding`, `ingress` (if any)

- **Artifact Registry inventory snapshot**:
  - `audit_artifacts/artifacts_snapshot.json`
  - Tags + digests + create times (for audit and “missing image” diagnosis)

### Scenarios

#### Cluster corrupted / cluster deleted

1) Recreate the cluster using your existing infra scripts (GKE) and re-authenticate `kubectl` to the new cluster.
2) Ensure the v2 namespace exists (LKG manifest includes it).
3) Restore to LKG (see “Restore runbook”).
4) Verify health and keep execution disabled.

#### Bad deploy (regression)

1) **Do not roll forward** blindly.
2) Restore to LKG to return to a known-good digest set.
3) Capture a new LKG only after validation.

#### Missing images / Artifact Registry cleanup

1) Run `scripts/snapshot_artifacts.sh`.
2) Compare the digests in `ops/lkg/lkg_metadata.json` vs the registry inventory.
3) If a digest is missing, you must rebuild and push a new immutable digest, then re-capture LKG from the corrected running state.

#### Config drift

1) Run `scripts/backup_cluster_state.sh` to capture current drifted state.
2) Restore to LKG (server-side apply) to re-converge.
3) Audit differences via Git diffs on the snapshot artifacts if needed.

### Restore runbook (step-by-step)

#### 0) Preconditions

- You have the correct kube context pointing at the intended cluster.
- Execution is disabled via kill switch (restore enforces it).

#### 1) Restore to LKG

```bash
./scripts/restore_lkg.sh trading-floor
```

#### 2) Verify health

- Review the generated report:
  - `deploy_logs/health_report.md`
- Basic checks:

```bash
kubectl -n trading-floor get pods -o wide
kubectl -n trading-floor get deploy,sts
kubectl -n trading-floor get cm agenttrader-kill-switch -o jsonpath='{.data.EXECUTION_HALTED}{"\n"}'
```

Expected:
- Deployments/StatefulSets are Ready/Available.
- Kill switch prints **`1`** (execution halted).

#### 3) Post-restore: keep execution disabled

- Do not set `EXECUTION_HALTED` back to `0` as part of DR.
- If you need to perform further testing, do so in non-execution / sandbox modes only.

### Routine operations

#### Capture a new LKG (after validating a good release)

```bash
./scripts/capture_lkg.sh trading-floor
```

#### Create a cluster state backup

```bash
./scripts/backup_cluster_state.sh trading-floor
```

#### Snapshot Artifact Registry inventory

```bash
PROJECT=agenttrader-prod LOCATION=us-east4 AR_REPOS=trader-repo ./scripts/snapshot_artifacts.sh
```

