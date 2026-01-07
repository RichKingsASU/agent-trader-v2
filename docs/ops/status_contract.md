# Ops Status Contract (AgentTrader v2)

Goal: a UI (or deployment report) can show **calm, deterministic** operational states across:
- marketdata
- strategy-engine
- execution-agent (often scaled to 0)
- ingest jobs
- overall “Trading Floor”

This contract is implemented in `backend/ops/status_contract.py` and exposed by services at:
- `GET /ops/status`

## JSON schema (example shape)

```json
{
  "service_name": "marketdata-mcp-server",
  "service_kind": "marketdata",
  "repo_id": "RichKingsASU/agent-trader-v2",
  "git_sha": "abc123",
  "build_id": null,
  "agent_identity": {
    "agent_name": "marketdata-mcp-server",
    "agent_role": "marketdata",
    "agent_mode": "STREAM"
  },
  "status": {
    "state": "OK",
    "summary": "Healthy",
    "reason_codes": [],
    "last_updated_utc": "2026-01-07T12:00:00Z"
  },
  "heartbeat": {
    "last_heartbeat_utc": "2026-01-07T12:00:00Z",
    "age_seconds": 0.0,
    "ttl_seconds": 60
  },
  "marketdata": {
    "last_tick_utc": "2026-01-07T12:00:00Z",
    "last_bar_utc": null,
    "stale_threshold_seconds": 120,
    "is_fresh": true
  },
  "safety": {
    "kill_switch": false,
    "safe_to_run_strategies": true,
    "safe_to_execute_orders": false,
    "gating_reasons": []
  },
  "endpoints": {
    "healthz": "/health",
    "heartbeat": null,
    "metrics": null
  }
}
```

## Truth table (single deterministic semantics)

States: `OK | DEGRADED | HALTED | MARKET_CLOSED | OFFLINE | UNKNOWN`

Key rules (in priority order):
- **UNKNOWN**: only when required fields are missing (contract cannot be trusted).
- **OFFLINE (execution)**: `execution_enabled=false` or `execution_replicas=0` → OFFLINE (not an error).
- **OFFLINE (general)**: process not up / not reachable.
- **HALTED**: process is up AND kill-switch is true.
- **Market-hours awareness**:
  - if market is closed and the service is otherwise healthy → **MARKET_CLOSED** (not DEGRADED).
- **Marketdata freshness during market hours**:
  - marketdata stale/missing → **DEGRADED** for `marketdata`
  - marketdata stale/missing → **HALTED** for `strategy` (and execution runtime)

Reason codes are stable strings (examples):
- `KILL_SWITCH`
- `MARKET_CLOSED`
- `MARKETDATA_STALE`
- `MARKETDATA_MISSING`
- `EXECUTION_DISABLED`
- `REQUIRED_FIELDS_MISSING`

## Examples (what the UI should show)

### OK during market hours
- `status.state=OK`
- `reason_codes=[]`

### MARKET_CLOSED after hours
- `status.state=MARKET_CLOSED`
- `reason_codes=["MARKET_CLOSED"]`

### DEGRADED marketdata stale
- `service_kind=marketdata`
- `status.state=DEGRADED`
- `reason_codes=["MARKETDATA_STALE"]`

### HALTED kill-switch
- `status.state=HALTED`
- `reason_codes=["KILL_SWITCH"]`

### OFFLINE execution-agent (scaled 0)
- `service_kind=execution`
- `status.state=OFFLINE`
- `reason_codes=["EXECUTION_DISABLED"]`

