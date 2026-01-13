## Order lifecycle validation (options)

### Scope

Validated the **canonical lifecycle** and implementation hooks for broker orders intended for **options** (i.e., `OrderIntent(asset_class="OPTIONS")`) in the execution engine.

### Required transitions (spec)

- `NEW → ACCEPTED → (FILLED | CANCELLED | EXPIRED)`

### State diagram

See `docs/ORDER_LIFECYCLE_OPTIONS.md`.

### Findings

- **broker_order_id propagation**: present
  - `ExecutionResult.broker_order_id` is set from broker response `order["id"]` (`backend/execution/engine.py`).
  - Execution API returns `broker_order_id` to callers (`backend/services/execution_service/app.py`).
  - Ledger writes include `broker_order_id` (via `_FirestoreLedger.write_fill`).

- **Partial fills**: handled
  - Execution engine now converts cumulative `filled_qty` snapshots into **incremental deltas** (best-effort, in-memory) to avoid double-counting repeated polls within a process lifetime.

- **Lifecycle transitions**: validated
  - Canonical lifecycle + transition validation implemented in `backend/execution/order_lifecycle.py`.
  - Engine updates lifecycle on `place_order`, `cancel`, and `get_order_status` polls.

### Missing transitions (current)

- **None in canonical state machine** (required edges are supported and covered by tests).
- **Operational note**: broker-side `EXPIRED` and `CANCELLED` transitions are only observable when the system receives a broker update (e.g., via polling or broker event stream). The engine currently updates lifecycle on explicit `sync_and_ledger_if_filled()` polls and `cancel()` calls.

