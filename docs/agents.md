# Agent identity + intent logging (institutional audit trail)

AgentTrader v2 services emit **structured JSON logs** to stdout (Cloud Logging friendly) with:

- **Agent identity**: who is acting (`REPO_ID`, `AGENT_NAME`, `AGENT_ROLE`, `AGENT_MODE`, `AGENT_VERSION`)
- **Correlation**: how events relate (`correlation_id`, propagated via headers where applicable)
- **Intent logs**: why actions happened (replay-friendly `intent_*` schema)

## Agent Identity contract (required env vars)

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

