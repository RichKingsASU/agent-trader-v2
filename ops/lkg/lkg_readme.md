## AgentTrader v2 — Last Known Good (LKG)

This folder holds the **Last Known Good (LKG)** marker for the Kubernetes “trading floor” deployment.

LKG is used for **deterministic restore** after:
- cluster breakage or accidental deletion
- bad deploy / regressions
- configuration drift

### What LKG contains

- `lkg_manifest.yaml`
  - A Kubernetes apply-able manifest (stored as deterministic JSON, which is valid YAML 1.2).
  - Includes the v2 namespace resources plus the running v2 Deployments/StatefulSets **pinned to image digests** (no tags).
  - Includes the kill-switch ConfigMap set to **execution halted**.

- `lkg_metadata.json`
  - Timestamp, git SHA, build ID (if provided), cluster/namespace, and the component→digest inventory.
  - Records the safety posture used for restores.

### How it’s used

- **Capture LKG from the running cluster**:
  - `scripts/capture_lkg.sh`
  - This reads live resources + pod image digests and writes deterministic LKG files.

- **Restore to LKG** (safe-by-default):
  - `scripts/restore_lkg.sh`
  - Server-side applies the LKG manifest, waits for rollouts, enforces kill-switch “halted”, then runs `scripts/deploy_report.sh`.

### Safety note (absolute rule)

LKG restore is designed to **keep execution disabled** by forcing the kill switch:
- `agenttrader-kill-switch` → `EXECUTION_HALTED="1"`

