# Execution Engine

This repo enforces **strict separation**:

- **Strategies emit order intents** (desired action).
- **Execution decides** whether/when/how to place orders (risk checks + broker routing).
- **Everything is logged** for audit.

---

## Components

### `backend/execution/engine.py`

Contains:

- **`OrderIntent`**: strategy → execution contract
- **`RiskManager` / `RiskConfig`**: risk validation (fail-closed by default)
- **`Broker` interface**:
  - `place_order()`
  - `cancel_order()`
  - `get_order_status()`
- **`AlpacaBroker`**: minimal Alpaca Trading v2 REST implementation
- **`DryRunBroker`**: never routes orders
- **`ExecutionEngine`**: orchestration + audit logging + ledger writes

---

## Risk rules (current)

Implemented in `RiskManager`:

- **Kill switch**
  - **Preferred**: Env `EXECUTION_HALTED=1`
  - **Recommended for K8s**: mount a ConfigMap key as a file and set:
    - `EXECUTION_HALTED_FILE=/etc/agenttrader/kill-switch/EXECUTION_HALTED`
    - File contents: `1` to halt, `0` to allow
  - Optional (legacy): Firestore doc via `EXECUTION_HALTED_DOC` (or legacy `EXEC_KILL_SWITCH_DOC`)
- **Max daily trades**
  - Counts docs in Firestore `ledger_trades` for `(broker_account_id, trading_date)`
- **Max position size**
  - Reads `public.broker_positions` from Postgres (requires `DATABASE_URL`)
  - Compares projected post-trade position vs `EXEC_MAX_POSITION_QTY`

Safety behavior:

- **Fail-closed by default**: if required risk data can’t be fetched, the intent is rejected with `risk_data_unavailable`.
- To override (not recommended), set `EXEC_RISK_FAIL_OPEN=true`.

---

## Ledger writes (fills)

On any fill (or partial fill), execution writes/updates a Firestore document:

- **Collection**: `ledger_trades`
- **Document ID**: `broker_order_id`

Stored fields include:

- intent fields: `strategy_id`, `broker_account_id`, `symbol`, `side`, `qty`, `order_type`, etc.
- fill fields: `filled_qty`, `filled_avg_price`, `filled_at`
- audit blobs: `raw_broker_order`, `raw_fill`

Idempotency:

- Writes use `set(..., merge=True)` so repeated fill syncs update the same doc.
- Alpaca orders are placed with `client_order_id = client_intent_id` to preserve intent→execution traceability.

---

## Dry-run mode (required)

Dry-run is controlled by:

- `EXEC_DRY_RUN=1` (default is **enabled** unless explicitly set to false)

In dry-run:

- Risk checks still run
- Orders are **not** routed
- The engine returns `ExecutionResult(status="dry_run")`
- Ledger is **not** written unless a real broker fill occurs (by definition, it won’t in dry-run)

---

## Environment variables

### Risk

- `EXEC_MAX_POSITION_QTY` (float, default `100`)
- `EXEC_MAX_DAILY_TRADES` (int, default `50`)
- `EXECUTION_HALTED` (bool-like, default `0`) – **global kill switch**
- `EXECUTION_HALTED_FILE` (string, optional) – path to kill switch file (ideal for ConfigMap volume mounts)
- `EXECUTION_HALTED_DOC` (string, optional) – Firestore kill switch doc path (legacy/optional)
- (deprecated) `EXEC_KILL_SWITCH` / `EXEC_KILL_SWITCH_FILE` / `EXEC_KILL_SWITCH_DOC` – still honored for back-compat
- `EXEC_RISK_FAIL_OPEN` (bool-like, default `false`)

### Execution

- `EXEC_DRY_RUN` (bool-like, default `true`)

### Execution agent safety gate (Cloud Run service)

When using the execution service (`backend/services/execution_service/app.py`) for **live** trading
(`EXEC_DRY_RUN=0`), the service enforces an explicit agent state machine gate:

- Live trading is refused unless:
  - `AGENT_MODE=LIVE`
  - agent state is `READY`
  - execution kill-switch is OFF

See `docs/EXECUTION_AGENT_STATE_MACHINE.md`.

### Broker / data sources

- Alpaca:
  - `ALPACA_API_KEY`
  - `ALPACA_SECRET_KEY`
  - `ALPACA_TRADING_HOST` (defaults to paper host)
- Postgres:
  - `DATABASE_URL` (for `public.broker_positions`)
- Firestore:
  - `FIREBASE_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`)
  - ADC credentials via `GOOGLE_APPLICATION_CREDENTIALS` (or workload identity on Cloud Run)

---

## Example usage (Python)

```python
from backend.execution.engine import ExecutionEngine, OrderIntent, AlpacaBroker, DryRunBroker

engine = ExecutionEngine(
    broker=DryRunBroker(),  # swap to AlpacaBroker() when ready
    broker_name="alpaca",
    dry_run=True,
)

intent = OrderIntent(
    strategy_id="delta_momentum_v1",
    broker_account_id="paper",
    symbol="SPY",
    side="buy",
    qty=1,
    order_type="market",
)

result = engine.execute_intent(intent=intent)
print(result.status, result.risk.allowed, result.risk.reason)
```

