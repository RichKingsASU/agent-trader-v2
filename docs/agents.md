# Agent identity + intent logging

All agent runtimes should emit **one JSON log line at process startup** via:

- `backend.common.agent_boot.configure_startup_logging(agent_name, intent)`

## Safety Model (Global Kill-Switch + Health Contracts)

AgentTrader v2 is **fail-closed by default**. If anything is missing, unknown, or unparseable, the system defaults to **halted**.

### Global kill-switch

- **Single source of truth**: `ConfigMap` `agenttrader-safety` (namespace `trading-floor`)
  - `KILL_SWITCH`: `"true"` / `"false"`
  - `STALE_THRESHOLD_SECONDS`: `"30"` default
- **Fail-closed default**: if config is missing/unparseable ⇒ `KILL_SWITCH=true` (halted)
- **Behavior**:
  - When `KILL_SWITCH=true`, all safety evaluation reports **halted** and strategies **skip cycles**.

### Stale marketdata gating

- `marketdata-mcp-server` exposes:
  - `GET /heartbeat` ⇒ returns `last_marketdata_ts` and freshness (`fresh`/`stale`)
  - `GET /healthz` ⇒ unified health status (`ok`/`degraded`/`halted`)
- `strategy-engine`:
  - Fetches `GET http://marketdata-mcp-server/heartbeat` at the start of each cycle
  - If marketdata is **missing** or **stale**, it emits an intent log `intent_type="strategy_cycle_skipped"` and does **no strategy evaluation**

### Health statuses

- **`ok`**: safe to run strategy cycles (kill-switch off and marketdata fresh)
- **`degraded`** (marketdata only): service is up but marketdata is stale/missing
- **`halted`**: kill-switch enabled OR stale/missing marketdata gating prevents strategy cycles

Health endpoint HTTP semantics:
- `GET /readyz` and `GET /healthz` return **200 only when `status=="ok"`**, else **503**
- `GET /livez` returns **200 whenever the process is alive** (never flaps due to market closure)

## How to flip the kill-switch (Kubernetes)

Edit the ConfigMap:

```bash
kubectl -n trading-floor edit configmap agenttrader-safety
```

Set:
- `KILL_SWITCH: "true"` to halt strategy cycles
- `KILL_SWITCH: "false"` to allow strategy cycles (still gated on marketdata freshness)

If the ConfigMap is mounted as a volume, changes are reflected on disk automatically; the services also re-read config values during request handling / cycle preflight.

## Required fields

- **`ts`**: RFC3339/ISO8601 UTC timestamp for the startup log line
- **`agent_name`**: stable agent/service identifier (e.g. `execution-engine`)
- **`intent`**: one-sentence description of what this process is doing
- **`git_sha`**: git commit SHA (set via `GIT_SHA` env var; falls back to common CI vars)
- **`agent_mode`**: `dry_run` / `live` / `unknown` (or explicitly set via `AGENT_MODE`)
- **`environment`**: deployment environment (e.g. `prod`, `staging`, `dev`)

## Optional fields (included when available)

- **`service`**: Cloud Run service name (`K_SERVICE`) or explicit `SERVICE`
- **`workload`**: Kubernetes workload/pod name, or explicit `WORKLOAD`

## Example startup log line

```json
{"ts":"2026-01-06T12:34:56.789012+00:00","agent_name":"execution-engine","intent":"Serve the execution API; validate config and execute broker order intents.","git_sha":"a2466ec","agent_mode":"dry_run","environment":"prod","service":"execution-engine","workload":"execution-engine-7f7b6c7b6d-abcde"}
```

