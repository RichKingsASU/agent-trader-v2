# Safe Self-Shutdown (Production Reliability)

Objective: **ensure the system can stop itself safely** (SIGTERM / kill-switch / breakers) with a **graceful shutdown** that avoids starting new broker submissions during teardown (**no partial orders**).

This is a **safety-only** hardening: it does not change alpha logic or make market assumptions. Where thresholds are needed, they are **explicitly operator-configured**.

---

## Long-running loops (identified)

Below are the primary long-running loops in `backend/` (polling loops, `while True`, and background `*_loop` tasks). Many already rely on task cancellation / stop events; the key gaps were “bare” loops without a shared shutdown/killswitch gate.

### `while True` loops

- **`backend/streams/alpaca_trade_candle_aggregator.py`**: `_db_consumer()`, `_periodic_flush()`, `_periodic_ops()`
- **`backend/streams/alpaca_quotes_streamer.py`**: Alpaca quote stream reconnect loop
- **`backend/streams_bridge/main.py`**: `_heartbeat_loop()` (task)
- **`backend/streams_bridge/firestore_writer.py`**: retry/write loop
- **`backend/streams_bridge/streams/price_stream_client.py`**: stream reconnect loops
- **`backend/streams_bridge/streams/options_flow_client.py`**: stream reconnect loops
- **`backend/streams_bridge/streams/news_stream_client.py`**: stream reconnect loops
- **`backend/streams_bridge/streams/account_updates_client.py`**: stream reconnect loops
- **`backend/ingestion/firebase_writer.py`**: retry/write loop
- **`backend/persistence/firebase_writer.py`**: retry/write loop
- **`backend/persistence/firestore_retry.py`**: retry loop
- **`backend/strategy_runner/firecracker_api.py`**: API polling loop

### “stop-event / shutdown-flag” loops

- **`backend/strategy_engine/service.py`**: background cycle loop + readiness/heartbeat tasks
- **`backend/execution_agent/main.py`**: `iter_ndjson_follow()` file-follow loop
- **`backend/mission_control/main.py`**: polling loops / ops status
- **`backend/ingestion/*`**: service loops with `AsyncShutdown` / stop events
- **`backend/utils/ops_markers.py`**: `heartbeat_loop()` uses interruptible waits
- **`backend/strategies/options_bot.py`**: now uses an asyncio stop event and SIGTERM handlers (see below)

---

## Global kill-switch (locations + behavior)

Kill-switch contract is documented in `docs/KILL_SWITCH.md`:

- **Key**: `EXECUTION_HALTED` (truthy => halt execution)
- **Recommended**: `EXECUTION_HALTED_FILE=/etc/agenttrader/kill-switch/EXECUTION_HALTED` (ConfigMap-mounted file)

### Where the kill-switch is checked

- **Core kill-switch implementation**: `backend/common/kill_switch.py`
- **Broker-side execution boundary** (defense-in-depth):
  - `backend/execution/engine.py`: `require_kill_switch_off(operation="broker order placement")` before broker calls
- **Execution decision gating / ops visibility**:
  - `backend/services/execution_service/app.py`: kill-switch is reflected in `/ops/status` and request-time state gating
- **Strategy runtime (signal emission)**:
  - `backend/strategies/options_bot.py`: drops events + exits loop when kill-switch is active
- **Other read-only status surfaces**:
  - `backend/strategy_engine/service.py`, `backend/mission_control/main.py`, `backend/execution_agent/main.py`

---

## Per-strategy circuit breakers (conditions + configuration)

Safety breakers live in `backend/safety/strategy_breakers.py`.

### 1) Missing market data

- **Condition**: strategy inputs are missing (e.g. bars list empty)
- **Where enforced**:
  - `backend/strategy_engine/driver.py`: triggers `circuit_breaker_triggered` and forces a safe `flat` decision for that symbol
- **Market assumptions**: none (objective presence/absence check)

### 2) Abnormal volatility

- **Condition**: short-term realized volatility is abnormally high vs a baseline window, measured as:
  - \( ratio = \sigma_{recent} / \sigma_{baseline} \)
- **Where enforced**:
  - `backend/strategy_engine/driver.py` (bars-based strategies)
- **Configuration (disabled by default)**:
  - `STRATEGY_CB_VOL_RATIO_THRESHOLD`: set > 0 to enable (example: `3.0`)
  - `STRATEGY_CB_VOL_RECENT_N` (default `5`)
  - `STRATEGY_CB_VOL_BASELINE_N` (default `30`)
- **Market assumptions**: none baked-in (operator supplies the threshold)

### 3) Consecutive losses

- **Condition**: last realized (closing) events contain **N consecutive negative realized P&L** (ledger-based FIFO attribution)
- **Where enforced**:
  - `backend/services/execution_service/app.py` (request-time gate; only applies when `EXEC_DRY_RUN=0`)
- **Configuration (disabled by default)**:
  - `EXEC_CB_MAX_CONSECUTIVE_LOSSES`: set > 0 to enable (example: `3`)
- **Notes**:
  - The implementation uses ledger fill data and FIFO attribution (deterministic).
  - If breaker evaluation fails (e.g., Firestore unavailable), the request path logs and continues (best-effort safety telemetry).

---

## Graceful shutdown flow (no partial orders)

### Key guarantee

Once shutdown is initiated, the system will **refuse starting new broker submissions**, and will **briefly wait** for any already-started submission to finish before completing shutdown. This prevents “half-started” submissions at process teardown time.

### Components

- **Shutdown gate**: `backend/safety/shutdown_gate.py`
  - `request_shutdown(reason=...)`: marks shutdown requested (process-wide)
  - `OrderSubmissionGuard(...)`: wraps broker submissions; increments/decrements an in-flight counter
  - `wait_for_inflight_zero(timeout_s=...)`: best-effort drain wait

### Execution service shutdown sequence (`backend/services/execution_service/app.py`)

1. FastAPI shutdown event runs:
   - sets `app.state.shutting_down = True`
   - calls `request_shutdown(reason="fastapi_shutdown")`
2. Best-effort drain wait:
   - waits up to `EXEC_SHUTDOWN_DRAIN_TIMEOUT_S` (default `8s`) for in-flight submissions to finish

### Execution request flow (`/execute`)

1. If `app.state.shutting_down` is true:
   - return **HTTP 503** (`"shutting_down"`)
2. If live execution is enabled (not dry-run), circuit-breaker checks run before attempting any broker submission.

### Broker submission boundary (`backend/execution/engine.py`)

Right before calling the broker:

- checks shutdown gate (`shutdown_requested` => reject)
- checks `AGENT_MODE` authorization
- checks global kill-switch
- wraps submission in `OrderSubmissionGuard` to:
  - prevent new submissions after shutdown is requested
  - track in-flight submissions so shutdown can drain cleanly

### Strategy runtime example (`backend/strategies/options_bot.py`)

- Installs SIGTERM/SIGINT handlers to set an asyncio stop event.
- On kill-switch activation, exits the main loop promptly.
- Drains/closes NATS connection best-effort on exit.

---

## Operator runbook pointers

- Global kill-switch drill: `docs/KILL_SWITCH.md`
- Kubernetes default “halted” posture: `k8s/05-kill-switch-configmap.yaml` (`EXECUTION_HALTED: "1"`)

