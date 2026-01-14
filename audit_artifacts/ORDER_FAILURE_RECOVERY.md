# Order Failure Recovery (Options)

## Goals

- Detect **rejected**, **stale**, and **unfilled beyond timeout** option orders.
- **Cancel** timed-out open orders and **reconcile** persisted order state so strategy pipelines do not “think” an order is still live.

## Timeout rules

Configured via environment variables (defaults shown):

- `EXEC_ORDER_TIMEOUT_S_OPTIONS_MARKET` = **20s**
- `EXEC_ORDER_TIMEOUT_S_OPTIONS_LIMIT` = **120s**
- `EXEC_ORDER_TIMEOUT_S_DEFAULT_MARKET` = **15s**
- `EXEC_ORDER_TIMEOUT_S_DEFAULT_LIMIT` = **90s**
- `EXEC_ORDER_STALE_S` = **60s** (how long before an order is “stale” and should be re-polled)

Order timeouts are selected by:

- **asset_class**: `OPTIONS` uses the `OPTIONS_*` settings; everything else uses `DEFAULT_*`
- **order_type**: limit-like (`limit`, `stop_limit`) use `*_LIMIT`; others use `*_MARKET`

## Recovery logic

### Persistent order tracking

On successful submission, the execution service stores an “execution order record” at:

- `tenants/{tenant_id}/execution_orders/{client_intent_id}`

Key fields:

- `broker_order_id`, `status`, `status_norm`
- `asset_class` (inferred from request metadata)
- timestamps: `created_at`, `last_broker_sync_at`
- `intent_snapshot` (minimal intent + tenant/uid metadata needed for replay-safe reconciliation)

### Detection + actions

Recovery runs via the admin endpoint:

- `POST /orders/recover` (requires `EXEC_AGENT_ADMIN_KEY` and header `X-Exec-Agent-Key`)

For each open order record:

1. **Stale detection**
   - If `now - last_broker_sync_at >= EXEC_ORDER_STALE_S` (or `last_broker_sync_at` missing),
     poll broker status (`sync_and_ledger_if_filled`).

2. **Rejected detection**
   - If broker status is `rejected` (or any terminal failure status), mark the record terminal
     so downstream state machines can treat the intent as failed and move on.

3. **Unfilled beyond timeout**
   - If `now - created_at >= timeout_s` and status is still in an open state, **cancel** the order.
   - After cancel, best-effort re-poll once to capture terminal status and write any partial fill.

4. **Ledger reconciliation**
   - If broker shows `filled` / `partially_filled` (or `filled_qty > 0`), write the fill to the ledger using the stored `intent_snapshot`
     (critical for **OPTIONS**, where naive reconstruction defaults to equities).

### Stuck-order safety outcomes

- Open orders are either:
  - **observed filled** (ledger updated), or
  - **observed terminal** (rejected/canceled/expired), or
  - **forced terminal by timeout cancel**.

This prevents “poisoned strategy state” where an order is assumed live forever and blocks subsequent actions.

