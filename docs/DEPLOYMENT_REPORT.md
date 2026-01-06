## Deployment report generator (Kubernetes)

This repo includes a non-interactive deployment report generator that snapshots the current Kubernetes state into a single markdown file (pods, deployments, rollouts, images, warning events, and suggested scale-ups).

### Requirements

- `kubectl` installed and authenticated to the target cluster
- `python3` available (used for JSON → markdown formatting)

### Output

- **File**: `deploy_logs/health_report.md` (directory auto-created if missing)
- Note: `deploy_logs/` is gitignored by design.

## REPORT USAGE

Generate a report using your **current** kube context/namespace:

```bash
chmod +x ./scripts/deploy_report.sh
./scripts/deploy_report.sh
```

Generate a report for a specific namespace:

```bash
./scripts/deploy_report.sh whale-strategy
```

Generate a report with more warning events included:

```bash
EVENT_LIMIT=50 ./scripts/deploy_report.sh whale-strategy
```

Generate a report with a longer rollout wait (default: 10s):

```bash
ROLLOUT_TIMEOUT=30s ./scripts/deploy_report.sh whale-strategy
```

View the report:

```bash
cat deploy_logs/health_report.md
```

