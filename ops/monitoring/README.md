## AgentTrader v2 — Institutional Observability Pack

This folder ships **dashboards + alerts + (optional) log-based metrics** for Google Cloud Monitoring, designed to be:
- **Quiet** (low-noise, longer durations, rate limits)
- **Actionable** (each alert maps to a runbook)
- **SLO-aligned** (freshness, evaluation continuity, basic availability)

### Preconditions

- **No third-party tooling**: uses only GKE + Cloud Logging/Monitoring.
- **Metrics ingestion**: these configs assume **GKE Managed Service for Prometheus (GMP)** is enabled in your cluster.
  - If you don’t have GMP, you can still use `/metrics` directly for debugging, but Cloud Monitoring dashboards/alerts on Prometheus metrics won’t populate.

### What gets created

- **Prometheus scraping (GMP)**: `gmp/podmonitoring-*.yaml`
- **Dashboard**: `dashboards/agenttrader_v2_ops_dashboard.json`
- **Alert policies**: `alert_policies/*.json`
- **Optional log-based metrics**: `log_based_metrics/*.json` (Cloud Logging metrics)

### Apply (one-time / idempotent)

From repo root:

```bash
export PROJECT_ID="YOUR_GCP_PROJECT_ID"
export NAMESPACE="trading-floor"

# 1) Enable Prometheus scraping in-cluster (GMP)
./ops/monitoring/apply_gmp_scrape.sh "$NAMESPACE"

# 2) Create/update the dashboard
./ops/monitoring/apply_dashboards.sh "$PROJECT_ID"

# 3) Create/update alerting policies
./ops/monitoring/apply_alert_policies.sh "$PROJECT_ID"

# 4) (Optional) Create/update log-based metrics
./ops/monitoring/apply_log_based_metrics.sh "$PROJECT_ID"
```

### Notes on “market hours” gating

Cloud Monitoring alert policies don’t provide a clean “schedule” gate as code.
This pack:
- **ships sane defaults** (longer durations, low sensitivity)
- **documents where to tune**:
  - update thresholds/durations
  - or use Monitoring “mute configs” for off-hours (can be created later if your org standardizes them)

