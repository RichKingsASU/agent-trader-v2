# Strategy Marketplace — Firestore Schema (tenant-scoped)

This document defines a **Firestore-only** schema for a Strategy Marketplace where:
- strategies are **rentable**
- subscriptions connect **user ↔ strategy**
- **revenue share** terms define fee splits
- strategy performance is tracked **per subscriber** to compute fees

Design constraints:
- **Tenant-scoped** operational data under `tenants/{tid}/...`
- A future **global marketplace** is supported via a global published listing collection

---

## Text ERD (high-level)

```
marketplace_strategies (global)
  └─ marketplace_strategies/{strategy_id}
        ▲ referenced by
        │
tenants/{tid}
  ├─ subscriptions/{sub_id}  ────────────────┐
  │     - uid                                │
  │     - strategy_id                        │
  │     - start_at / end_at                  │
  │     - active                             │
  │     - revenue_share_term_id ───────────┐ │
  │                                        │ │
  ├─ revenue_share_terms/{term_id} ◄────────┘ │
  │
  ├─ ledger_trades/{trade_id}  (source of truth for P&L attribution)
  │     - uid
  │     - strategy_id
  │     - fees
  │
  ├─ strategy_performance/{perf_id}  (monthly snapshots)
        - user_id
        - strategy_id
        - subscription_id
        - period_start/end
        - realized_pnl, fees, net_profit
        - revenue_share_fee
  │
  └─ performance_fees/{fee_id}  (monthly fee records)
        - fee_amount
        - creator_amount / platform_amount / user_amount
```

---

## 1) Global listing: `marketplace_strategies/{strategy_id}`

### Purpose
Public (or broadly readable) marketplace listing used to discover and rent strategies.

### Document ID
- `{strategy_id}`: stable listing id (can differ from publisher’s internal strategy id)

### Schema (recommended)
- **`status`**: `string` (`draft` | `published` | `suspended` | `retired`)
- **`name`**: `string`
- **`description`**: `string|null`
- **`tags`**: `array<string>` (small/bounded)
- **`pricing`**: `map`
  - **`rent_cents_monthly`**: `number` (optional fixed rent)
  - **`revenue_share_bps_default`**: `number` (optional default revenue share, 0..10000)
- **`publisher`**: `map` (supports future global marketplace)
  - **`publisher_tenant_id`**: `string`
  - **`publisher_strategy_ref`**: `string` (recommended Firestore path like `tenants/{publisher_tid}/strategies/{sid}`)
  - **`publisher_user_id`**: `string|null` (optional)
- **`visibility`**: `map`
  - **`is_public`**: `boolean`
  - **`allowed_tenant_ids`**: `array<string>|null` (optional; bounded)
- **`created_at`**: `timestamp`
- **`updated_at`**: `timestamp`

Notes:
- For “global marketplace”, keep this collection at the root and ensure `publisher.publisher_tenant_id` is always set.
- Tenants subscribe to **the listing** (not necessarily the internal strategy doc), so listings can evolve/version without breaking subscriptions.

---

## 2) Tenant subscriptions: `tenants/{tid}/subscriptions/{sub_id}`

### Purpose
Connects a **subscriber user** to a **marketplace strategy listing** with a chosen revenue share term and billing lifecycle.

### Document ID
- `{sub_id}`: UUID/ULID recommended

### Schema (recommended)
- **`tenant_id`**: `string` (redundant, for auditing)
- **`uid`**: `string` (subscriber uid)
- **`strategy_id`**: `string` (doc id in `marketplace_strategies`)
- **`revenue_share_term_id`**: `string|null` (doc id in `tenants/{tid}/revenue_share_terms`)
- **`start_at`**: `timestamp`
- **`end_at`**: `timestamp|null`
- **`active`**: `boolean`
- **`billing`**: `map`
  - **`rent_cents_monthly`**: `number|null`
  - **`currency`**: `string` (e.g. `USD`)
- **`created_at`**: `timestamp`
- **`updated_at`**: `timestamp`

---

## 3) Revenue share terms: `tenants/{tid}/revenue_share_terms/{term_id}`

### Purpose
Defines how fees are computed and how revenue is split. Stored tenant-scoped so each tenant can offer different terms.

### Schema (recommended)
- **`tenant_id`**: `string`
- **`name`**: `string`
- **`status`**: `string` (`active` | `deprecated`)
- **`fee_period`**: `string` (`monthly`)  *(extend later)*
- **`fee_rate`**: `number` *(decimal, e.g. `0.20` for 20%)*
- **`creator_pct`**: `number` *(decimal fraction, e.g. `0.50` for 50%)*
- **`platform_pct`**: `number` *(decimal fraction, e.g. `0.30` for 30%)*
- **`user_pct`**: `number` *(decimal fraction, e.g. `0.20` for 20%)*
- **`high_water_mark`**: `map|null` (optional, future)
  - **`enabled`**: `boolean`
  - **`scope`**: `string` (`user_strategy`) etc.
- **`created_at`**: `timestamp`
- **`updated_at`**: `timestamp`

Constraints:
- `creator_pct + platform_pct + user_pct == 1.0`
- `fee_amount = realized_pnl × fee_rate`

---

## 4) Strategy performance snapshots: `tenants/{tid}/strategy_performance/{perf_id}`

### Purpose
Stores **monthly** performance per subscriber + strategy, used as the basis for invoicing and revenue share fees.

### Document ID
Recommended deterministic id to enforce idempotency:
- `{perf_id}` = `{uid}__{strategy_id}__YYYY-MM`

### Schema (recommended)
- **`tenant_id`**: `string`
- **`uid`**: `string`
- **`strategy_id`**: `string`
- **`subscription_id`**: `string|null`
- **`revenue_share_term_id`**: `string|null`
- **`period_start`**: `timestamp`
- **`period_end`**: `timestamp`
- **`trade_count`**: `number`
- **`realized_pnl`**: `number` *(derived from `ledger_trades`; define gross-vs-net explicitly in your ledger conventions)*
- **`fees`**: `number` *(broker/clearing fees; derived from `ledger_trades`)*
- **`net_profit`**: `number` = `realized_pnl - fees`
- **`fee_basis_type`**: `string` *(copied from term; default `net_profit_positive`)*
- **`fee_basis_amount`**: `number` *(typically `max(net_profit, 0)` when `fee_basis_type=net_profit_positive`)*
- **`revenue_share_fee`**: `number|null` *(computed from term + fee_basis_amount)*
- **`computed_at`**: `timestamp`
- **`source`**: `string` (e.g. `ledger_trades_fifo`)

---

## 5) Performance fee records: `tenants/{tid}/performance_fees/{fee_id}`

### Purpose
Stores **monthly** performance fees per subscription, including the **creator/platform/user** revenue split.

### Document ID
Recommended deterministic id to enforce idempotency:
- `{fee_id}` = `{subscription_id}__YYYY-MM`

### Schema (recommended)
- **`tenant_id`**: `string`
- **`subscription_id`**: `string`
- **`user_id`**: `string`
- **`strategy_id`**: `string`
- **`revenue_share_term_id`**: `string`
- **`period_start`**: `timestamp`
- **`period_end`**: `timestamp`
- **`realized_pnl`**: `number`
- **`fee_rate`**: `number`
- **`fee_amount`**: `number`
- **`creator_pct`**: `number`
- **`platform_pct`**: `number`
- **`user_pct`**: `number`
- **`creator_amount`**: `number`
- **`platform_amount`**: `number`
- **`user_amount`**: `number`
- **`computed_at`**: `timestamp`
- **`source`**: `string` (e.g. `strategy_performance_snapshot`)

## How to compute “profit strategy generated”

**Source of truth**: `tenants/{tid}/ledger_trades`

### Linkage
For a given tenant/month/subscriber/strategy:
- Use **fill-level** `ledger_trades` (one doc per fill) and group by:
  - `uid`
  - `strategy_id`

For correct monthly realized P&L, you must include fills from **before** the month too:
- Query all fills with `ts < period_end`
- Compute realized P&L as a **delta**:
  - `realized_in_period = realized(as_of=period_end) - realized(as_of=period_start)`
- Compute unrealized P&L as-of `period_end` using mark prices (per symbol).

---

## Supporting collection (required for computation): `tenants/{tid}/ledger_trades/{trade_id}`

This collection is the **attribution ledger** used to compute performance.

### Minimal schema (recommended)
- **`tenant_id`**: `string`
- **`uid`**: `string`
- **`strategy_id`**: `string`
- **`run_id`**: `string`
- **`symbol`**: `string`
- **`side`**: `string` (`buy`/`sell`)
- **`qty`**: `number`
- **`price`**: `number`
- **`ts`**: `timestamp`
- **`fees`**: `number`

---

## Indexing guidance (Firestore)

The monthly perf computation query filters by `(uid, strategy_id, ts < period_end)` and orders by `ts`.
This will require a composite index for:
- `uid` (asc), `strategy_id` (asc), `ts` (asc)

Firestore will usually prompt with an index creation link the first time the query runs.

