# Ops “Status Page” Contract (minimal, read-only)

Goal: allow an Ops UI to display **service state** without touching execution paths.

Services must expose:
- `GET /ops/status` on **strategy-engine**
- `GET /ops/status` on **marketdata-mcp-server**

## Contract (JSON schema)

Response is JSON with these fields (all fields always present; some may be `null`):

- **`uptime`**: number  
  Seconds since process start (monotonic, best-effort).
- **`last_heartbeat`**: string | null  
  RFC3339/ISO8601 UTC timestamp like `"2026-01-07T12:00:00Z"`.  
  For marketdata, this should prefer “last tick observed” when available.
- **`data_freshness_seconds`**: number | null  
  Seconds since the last relevant data observation.
  - marketdata-mcp-server: seconds since last tick (if any)
  - strategy-engine: best-effort marketdata freshness observed by the engine (if any)
- **`build_sha`**: string  
  Git commit SHA (or `"unknown"` if not provided).
- **`agent_mode`**: string  
  Process authority mode (e.g. `"OBSERVE"`, `"EVAL"`, `"PAPER"`). **Must not be `"EXECUTE"`.**

## Example response

```json
{
  "uptime": 12345.67,
  "last_heartbeat": "2026-01-07T12:00:00Z",
  "data_freshness_seconds": 2.4,
  "build_sha": "54afffe",
  "agent_mode": "OBSERVE"
}
```

## Safety constraints

- The endpoint is **read-only**: it must not place orders, trigger execution, or mutate external state.
- It must return quickly even when dependencies are degraded; unknown freshness should be expressed as `null`.

## Note (optional richer contract)

This repo also contains a richer, deterministic multi-block ops schema in `backend/ops/status_contract.py`.  
Services may return additional fields beyond this minimal contract, but the five keys above are the **stable** UI baseline.

