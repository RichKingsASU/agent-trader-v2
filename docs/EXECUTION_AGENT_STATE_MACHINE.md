# Execution Agent State Machine

This repo includes a small, explicit **agent state machine** used by execution agents to decide whether they are allowed to place *live* broker orders.

## States

- **INIT**: Agent just started; has not confirmed healthy inputs yet.
- **READY**: Agent is allowed to place live trades (subject to `AGENT_MODE` + kill-switch).
- **DEGRADED**: Agent is running, but critical dependencies are stale (ex: market data heartbeat stale). Live trading is refused.
- **HALTED**: Agent is halted by a kill-switch. Live trading is refused until kill-switch is cleared.
- **ERROR**: Agent hit an unexpected exception. Live trading is refused; optional exponential backoff is applied for retry/restart behavior.

## Explicit transitions

- **marketdata stale ⇒ DEGRADED**
- **kill-switch ⇒ HALTED**
- **recover ⇒ READY**
- **unexpected exception ⇒ ERROR** (with optional exponential backoff)

State transitions are emitted as structured log events:

- `agent.state_transition {...}`

## Where it’s enforced

The Cloud Run execution service (`backend/services/execution_service/app.py`) updates the state machine on each request and enforces:

- **Refuse live trading unless**:
  - `state == READY`
  - `AGENT_MODE == LIVE`
  - kill-switch is **OFF**

Notes:
- If `EXEC_DRY_RUN=1`, the service never routes orders to the broker, so requests are allowed even when not `LIVE`.
- If `EXEC_DRY_RUN=0`, the service will hard-refuse `/execute` unless the policy above passes.

## Inputs used by the agent

### Kill-switch

Execution kill-switch is checked via `RiskManager`:

- **Env**: `EXEC_KILL_SWITCH=1`
- **Firestore** (optional): `ops/execution_kill_switch` with `{ "enabled": true }`

### Marketdata freshness (staleness)

Market ingest heartbeat is read from Firestore:

- Preferred (tenant-scoped): `tenants/{tenant_id}/ops/market_ingest`
- Fallback (legacy/global): `ops/market_ingest`

Field:
- `ts`: Firestore Timestamp (or ISO string) written by ingestion.

Staleness threshold:
- `MARKETDATA_STALE_THRESHOLD_S` (default: `120`)

## Service endpoints (debug/ops)

### `GET /state`

Returns current state machine state + key gating inputs (agent mode, kill-switch, marketdata heartbeat age).

### `POST /recover`

Forces `recover ⇒ READY` (does **not** override `HALTED`).

Optional protection:
- If `EXEC_AGENT_ADMIN_KEY` is set, callers must pass header:
  - `X-Exec-Agent-Key: <EXEC_AGENT_ADMIN_KEY>`

## “STATE MACHINE TEST” (manual)

These steps validate the two critical transitions: **stale market data ⇒ DEGRADED** and **kill-switch ⇒ HALTED**.

### 1) Observe baseline state

Start the execution service and query:

```bash
curl -sS http://localhost:8000/state | jq .
```

Expected:
- `state` becomes **READY** when marketdata heartbeat is fresh and kill-switch is off.

### 2) Simulate **marketdata stale ⇒ DEGRADED**

Pick one approach:

- **Option A (recommended)**: stop the market-ingest service (or scale it to 0) and wait longer than `MARKETDATA_STALE_THRESHOLD_S`.
- **Option B**: in Firestore, edit the market ingest heartbeat document and set `ts` to an old timestamp:
  - `tenants/{tenant_id}/ops/market_ingest.ts` (preferred), or
  - `ops/market_ingest.ts` (fallback)

Then check:

```bash
curl -sS http://localhost:8000/state | jq .state
```

Expected:
- `state == "DEGRADED"`
- Logs include an `agent.state_transition` event with `trigger="marketdata_stale"`.

If you attempt live trading while degraded (with `EXEC_DRY_RUN=0`), it should refuse:

```bash
curl -sS -X POST http://localhost:8000/execute \
  -H "Content-Type: application/json" \
  -d '{"strategy_id":"s1","broker_account_id":"acct1","symbol":"SPY","side":"buy","qty":1,"metadata":{"tenant_id":"t1"}}'
```

Expected:
- HTTP **409** with `reason` like `agent_state_not_ready:DEGRADED`.

### 3) Simulate **kill-switch ⇒ HALTED**

Pick one approach:

- **Option A**: set env var `EXEC_KILL_SWITCH=1` for the execution service and restart it.
- **Option B**: set Firestore doc `ops/execution_kill_switch` to `{ "enabled": true }`.

Then check:

```bash
curl -sS http://localhost:8000/state | jq .state
```

Expected:
- `state == "HALTED"`
- Logs include `agent.state_transition` with `trigger="kill_switch"`.

### 4) Recover ⇒ READY

To recover from **DEGRADED**:
- Restore market-ingest heartbeat freshness (restart market-ingest service), then call:

```bash
curl -sS -X POST http://localhost:8000/recover | jq .
```

Expected:
- `state == "READY"` (as long as kill-switch is **off**).

To recover from **HALTED**:
- **First** disable the kill-switch (env or Firestore), then call `/recover`.

## Related code

- `backend/common/agent_state_machine.py`: shared state machine + policy gate
- `backend/execution/marketdata_health.py`: market ingest heartbeat staleness check
- `backend/services/execution_service/app.py`: enforcement + `/state` + `/recover`

