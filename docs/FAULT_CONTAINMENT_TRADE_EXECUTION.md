# Fault Containment: Trade Execution Cleanup Guarantees

Objective: **a failed trade must not poison the system** (no stuck locks / stuck reservations / blocked future trades).

This repository has multiple “trade-ish” entry points; the one that actually routes to a broker is the **execution engine** (`backend/execution/engine.py`). The work below adds *explicit cleanup guarantees* in that execution path.

---

## Exception-path inventory (execution)

### Execution entrypoint
- **`ExecutionEngine.execute_intent()`** (`backend/execution/engine.py`)

Primary exception sources (by stage):
- **Pre-flight / telemetry**
  - Replay/audit logging (`dumps_replay_event`, `logger.info(...)`) – best-effort; exceptions already swallowed.
- **Smart routing**
  - Market data quote fetch / JSON parse / network errors inside `SmartRouter` – best-effort; returns allow/deny decision without raising.
- **Risk checks**
  - Firestore reads (daily trades count) inside `RiskManager.validate()`
  - Postgres connectivity / query failures inside `RiskManager.validate()`
  - Behavior depends on `fail_open` (default fail-closed).
- **Trading authority gate**
  - `require_trading_live_mode(...)` can raise `AgentModeError`
  - `require_kill_switch_off(...)` can raise `ExecutionHaltedError`
- **Broker call**
  - `broker.place_order(...)` can raise (timeouts, HTTP errors, client errors, serialization).
- **Post-submit side effects**
  - Ledger write / portfolio history write can raise (Firestore) but are already caught and logged (`exec.ledger_write_failed`).

### Other trade-related API entrypoint (strategy service)
- **`POST /trades/execute`** (`backend/strategy_service/routers/trades.py`)

Primary exception sources:
- **Risk service call**: `requests.post(...).raise_for_status()` can raise network/HTTP exceptions → currently surfaced as HTTP 500.
- **Shadow-mode write path**:
  - Firestore reads (shadow-mode flag, quotes)
  - Firestore writes (shadow trade creation)
- **Live/paper path**:
  - Firestore writes (`insert_paper_order`)

Note: this endpoint currently does not reserve capital or acquire a lock, so the “poisoning” risk there is primarily **partial writes** or **HTTP 500s**, not leaked reservations. The explicit cleanup guarantee added in this change targets the execution engine, where broker submission is performed.

---

## Cleanup guarantees added

### What “reservation” means here
This change introduces a **short-lived in-flight reservation** that exists only to support cleanup guarantees and failure containment:
- It is *acquired at the start of execution*.
- It is *released in a `finally` block* on **every return path** and on **every exception path**.

It does **not** add retries and does **not** add queues.

### Implementation
- **`backend/execution/reservations.py`**
  - `ReservationManager` + `ReservationHandle` contracts
  - `BestEffortReservationManager`: ensures reservation acquisition never blocks trading (fail-open).
  - `FirestoreReservationManager`: records in-flight reservations at:
    - `tenants/{tenant_id}/execution_reservations/{client_intent_id}`
  - `ReservationHandle.release(...)` is designed to be **idempotent** and **non-throwing**.

- **`backend/execution/engine.py`**
  - `ExecutionEngine.execute_intent()` now wraps the whole execution flow in an outer:
    - `try: ... return ...`
    - `except: ... raise`
    - `finally: reservation.release(...)`

This creates an explicit guarantee:
\[
\text{reservation acquired} \Rightarrow \text{reservation released} \quad \text{(even if an exception is raised)}
\]

---

## Failure containment proof (tests)

### Proof strategy
If a failed trade “poisons” the system, it usually happens because:
- an exception occurs after a reservation/lock is created, and
- cleanup is skipped (no `finally`), leaving stuck state that blocks later trades.

We prove containment by forcing exceptions at each boundary and asserting `release()` was called exactly once.

### Unit tests
- **`tests/test_trade_execution_cleanup.py`**
  - `test_cleanup_releases_on_broker_exception`: broker throws → reservation released with `outcome="exception"`.
  - `test_cleanup_releases_on_agent_mode_error`: agent mode guard throws → reservation released with `outcome="exception"`.
  - `test_cleanup_releases_on_risk_reject`: early return rejected → reservation released with `outcome="rejected"`.
  - `test_cleanup_releases_on_dry_run`: early return dry_run → reservation released with `outcome="dry_run"`.

Note: the execution environment running this agent didn’t have `pytest` installed and lacked outbound network access to fetch it, so the tests couldn’t be executed here, but the test suite is self-contained and intended to run in CI where dependencies are available.

