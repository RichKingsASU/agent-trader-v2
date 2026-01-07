## Mission Control (read-only ops console API)

Lightweight FastAPI service that aggregates operational signals across AgentTrader services and exposes a **single read-only API** suitable for a future UI.

### Guarantees / constraints

- **Read-only only**: no endpoints to flip kill-switch or enable execution.
- **Best-effort polling**: unreachable agents are marked `OFFLINE`; Mission Control stays up.
- **Internal-by-default**: intended for in-cluster access via `ClusterIP`.

### Local run (dev)

Set an agents config path and run:

```bash
export AGENTS_CONFIG_PATH=/app/configs/agents/agents.yaml
uvicorn backend.mission_control.main:app --host 0.0.0.0 --port 8080
```

### Environment variables

- `AGENTS_CONFIG_PATH`: default `/app/configs/agents/agents.yaml`
- `POLL_INTERVAL_SECONDS`: default `10`
- `PER_AGENT_TIMEOUT_SECONDS`: default `1.5`
- `POLL_MAX_CONCURRENCY`: default `10`
- `EVENT_BUFFER_MAXLEN`: default `500`
- `DEPLOY_REPORT_PATH`: default `/var/agenttrader/reports/deploy_report.md`
- `EXECUTION_HALTED` / `EXECUTION_HALTED_FILE`: kill-switch state inputs (read-only)

### Endpoints (v1)

- `GET /api/v1/agents`
- `GET /api/v1/agents/{agent_name}`
- `GET /api/v1/safety`
- `GET /api/v1/reports/deploy/latest`
- `GET /api/v1/events/recent`

