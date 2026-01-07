# Agent identity + intent logging (institutional audit trail)

AgentTrader v2 services emit **structured JSON logs** to stdout (Cloud Logging friendly) with:

- **Agent identity**: who is acting (`REPO_ID`, `AGENT_NAME`, `AGENT_ROLE`, `AGENT_MODE`, `AGENT_VERSION`)
- **Correlation**: how events relate (`correlation_id`, propagated via headers where applicable)
- **Intent logs**: why actions happened (replay-friendly `intent_*` schema)

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

All runtimes must set:

- **`REPO_ID`**: must exist (e.g. `agent-trader-v2`)
- **`AGENT_NAME`**: stable service id (e.g. `marketdata-mcp-server`, `strategy-engine`)
- **`AGENT_ROLE`**: coarse responsibility (e.g. `marketdata`, `strategy_eval`, `execution`, `ops`)
- **`AGENT_MODE`**: `OFF` / `OBSERVE` / `EXECUTE` (mode is *logged only*; behavior is not changed here)

Optional:

- **`AGENT_VERSION`**: defaults to git sha (or `unknown`)

Identity is validated fail-fast via `backend.observability.agent_identity.require_identity_env()`.

## Intent log schema (required keys)

Every intent log line includes:

- **`timestamp`** (auto), **`level`**
- **`repo_id`**, **`agent_name`**, **`agent_role`**, **`agent_mode`**, **`git_sha`**
- **`intent_id`** (uuid4)
- **`correlation_id`**, **`trace_id`**
- **`intent_type`**, **`intent_summary`**, **`intent_payload`** (redacted)
- **`outcome`**: `started` | `success` | `failure`
- **`duration_ms`** (when measurable)
- **`error`** (sanitized, on failure)

Redaction is automatic (common secret keys: `*key*`, `*token*`, `*secret*`, `*password*`, `*authorization*`, `*cookie*`).

## Agents (v2 workloads)

### `marketdata-mcp-server`

- **`AGENT_NAME`**: `marketdata-mcp-server`
- **`AGENT_ROLE`**: `marketdata`
- **Intent logs emitted**:
  - `agent_start` (startup identity banner)
  - `subscription_connect_attempt` (connect/subscribe attempt)
  - `data_batch_received` (rate-limited quote ingest)
  - `marketdata_emit` (persist/publish downstream, e.g. Postgres)

### `strategy-engine`

- **`AGENT_NAME`**: `strategy-engine`
- **`AGENT_ROLE`**: `strategy_eval`
- **Intent logs emitted**:
  - `agent_start` (startup identity banner)
  - `strategy_evaluation_cycle` (cycle start/end)
  - `signal_produced` (strategy signal produced; may be `flat`)
  - `order_proposal` (**non-executing**) (would-place-order decision path)

## How to trace an incident

- **Find the `intent_id`** for the suspicious action (e.g. an `order_proposal`).
- **Follow the `correlation_id`** across services (HTTP callers can pass `X-Correlation-Id`).
- **Confirm outcome**:
  - `outcome=failure` with `error.message` indicates what failed (sanitized).
  - `duration_ms` helps isolate slow components.

## Example intent logs (single-line JSON)

```json
{"timestamp":"2026-01-07T00:00:00+00:00","level":"INFO","repo_id":"agent-trader-v2","agent_name":"strategy-engine","agent_role":"strategy_eval","agent_mode":"OFF","git_sha":"a2466ec","correlation_id":"2c0d3b2d-9b21-4c5a-9a8b-1ed3a6d8c7d0","trace_id":"2c0d3b2d-9b21-4c5a-9a8b-1ed3a6d8c7d0","intent_id":"d2cf0282-90da-4b9d-b48f-79f1d8f9c4ae","intent_type":"order_proposal","intent_summary":"Proposed order based on strategy decision (non-executing).","intent_payload":{"symbol":"SPY","side":"buy","size":1,"notional":495.12,"would_execute":false},"outcome":"success","duration_ms":3}
```

