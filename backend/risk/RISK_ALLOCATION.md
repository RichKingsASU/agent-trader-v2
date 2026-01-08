# Deterministic Risk Allocation

This repo enforces **deterministic, centralized risk sizing** via a single canonical function:

- `backend/risk/risk_allocator.py::allocate_risk(strategy_id, signal_confidence, market_state)`

## Guarantees

- **Determinism**: Same inputs → same outputs (pure function; no randomness).
- **No hidden globals**: The allocator does **not** read env vars, time, DB, or module state.
- **Safety invariants** (enforced with post-constraint assertions):
  - **Daily cap**: \(\sum \text{allocated\_usd} \le \text{daily\_risk\_cap\_usd}\)
  - **Per-strategy max**: \(\text{allocated\_usd} \le \text{max\_strategy\_allocation\_pct} \times \text{daily\_risk\_cap\_usd}\)

## How sizing works

Upstream strategy code may produce a *requested* size (e.g., `requested_notional_usd`).
The allocator **does not try to “optimize profit”** and it **does not alter signal direction**.
It only applies deterministic constraints to ensure portfolio safety.

## Caller responsibilities

Because the allocator has no hidden globals, callers must pass the relevant context in `market_state`:

- `daily_risk_cap_usd` **or** (`buying_power_usd` + `daily_risk_cap_pct`)
- `max_strategy_allocation_pct`
- `current_allocations_usd` (if enforcing cross-strategy aggregate caps)
- `requested_notional_usd` (or `requested_allocation_pct`)

## Integrations updated

- `backend/alpaca_signal_trader.py`: LLM/Vertex notional requests are now routed through `allocate_risk` before execution-oriented signals are emitted.
- `backend/strategy_engine/sentiment_strategy_driver.py`: fixed-size notional is now routed through `allocate_risk` (preserving legacy sizing while making constraints canonical).

