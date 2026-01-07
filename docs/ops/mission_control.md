## Mission Control (Agent Mission Control API)

Mission Control is a lightweight, **read-only** operational control plane API for AgentTrader v2. It provides a single place for a future UI (or humans with `curl`) to:

- list known agents/services
- see their last-known status (best-effort)
- view kill-switch state (read-only)
- view marketdata freshness summary (best-effort)
- fetch the latest deploy report markdown (if mounted)
- view recent Mission Control polling events (in-memory ring buffer)

### What it is (and isn’t)

- **Is**: read-only aggregator suitable for a UI later.
- **Is not**: a trading executor, a workflow engine, or a kill-switch controller.
- **No write endpoints** are implemented on purpose.

### Agent discovery

Agent inventory is currently **static**:

- `configs/agents/agents.yaml`

Each entry includes:

- `agent_name`
- `service_dns` (cluster URL)
- `kind` (`marketdata|strategy|execution|ingest`)
- `expected_endpoints` (e.g. `/ops/status`, `/healthz`, `/heartbeat`)
- `criticality` (`critical|important|optional`)

### Polling model

Mission Control polls agents every **10s** by default:

- `POLL_INTERVAL_SECONDS` (default `10`)
- per-agent request timeout: `PER_AGENT_TIMEOUT_SECONDS` (default `1.5`)
- failures degrade gracefully to `OFFLINE`

Each poll cycle records an in-memory event envelope (`mission_control.poll`) into a ring buffer of the last **500** events.

### API endpoints

- `GET /api/v1/agents`
  - returns inventory + last-known status (best-effort)
- `GET /api/v1/agents/{agent_name}`
  - returns detailed status including **redacted** raw `/ops/status` response (if available)
- `GET /api/v1/safety`
  - returns kill-switch state + marketdata freshness summary (best-effort)
- `GET /api/v1/reports/deploy/latest`
  - serves `DEPLOY_REPORT_PATH` as markdown text (default `/var/agenttrader/reports/deploy_report.md`)
- `GET /api/v1/events/recent?limit=N`
  - returns last N Mission Control poll events (newest-first, max 500)

### Deploy report ingestion (file-based)

Mission Control reads the latest report from:

- `/var/agenttrader/reports/deploy_report.md` (default)

In Kubernetes, mount a volume (PVC, hostPath, or ConfigMap-as-file) to `/var/agenttrader/reports`.

### Curl from inside the cluster

Assuming the Service name is `mission-control` in namespace `trading-floor`:

```bash
curl -sS http://mission-control.trading-floor.svc.cluster.local/api/v1/agents | jq
curl -sS http://mission-control.trading-floor.svc.cluster.local/api/v1/safety | jq
curl -sS http://mission-control.trading-floor.svc.cluster.local/api/v1/events/recent?limit=20 | jq
curl -sS http://mission-control.trading-floor.svc.cluster.local/api/v1/reports/deploy/latest
```

### How a future UI would consume it

A UI can:

- poll `GET /api/v1/agents` for the table view
- fetch `GET /api/v1/agents/{agent_name}` for drill-down detail
- show safety banner from `GET /api/v1/safety`
- show deploy report from `GET /api/v1/reports/deploy/latest`
- show recent activity from `GET /api/v1/events/recent`

