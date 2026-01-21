# AgentTrader v2 — Multi-Tenant Enterprise Readiness Specification

## Scope / goals

This document defines the **enterprise multi-tenant model** for AgentTrader v2:

- A clear tenancy model: **Tenant**, **User**, **Account**, **Strategy ownership**
- A canonical **Firestore namespace layout** with explicit **isolation guarantees**
- A practical design for **quota enforcement**
- A design for **per-tenant risk limits** and **per-tenant strategy enablement**

This spec intentionally aligns with the repo’s existing patterns:

- **User-scoped SaaS paths** under `users/{uid}/...` (current production model)
- **Org-style tenancy** under `tenants/{tenantId}/...` enforced by `firestore.rules` via a `tenant_id` auth claim + membership docs

---

## 1) Tenancy model

### 1.1 Tenant

A **Tenant** is the primary enterprise boundary and represents an organization (company, desk, fund, family office).

- **Tenant ID**: stable string (e.g. ULID, or slug-like `acme_capital`)
- **Primary boundary** for:
  - Data partitioning (`tenants/{tenantId}/...`)
  - Risk policy and enforcement
  - Strategy entitlements
  - Billing plans, quotas, and audit requirements
  - Shared resources (shared broker accounts, shared strategy configs)

**Tenant document**: `tenants/{tenantId}`

Recommended fields:
- `display_name`
- `created_at`
- `plan` (e.g. `trial`, `team`, `enterprise`)
- `status` (e.g. `active`, `suspended`)
- `default_region` (optional)

### 1.2 User

A **User** is a person identity represented by Firebase Auth UID.

- **User ID**: Firebase Auth `uid`
- A user may belong to **multiple tenants** (consultants, multi-org admins), but has **one active tenant context** per session (see Auth Context below).

**User document**: `users/{uid}`

Recommended fields:
- `email`
- `display_name`
- `created_at`
- `last_login_at`

### 1.3 Membership + roles

Membership is explicit and stored in Firestore to support:
- Access control (rules-level checks)
- Role-based authorization (admin/operator/viewer)
- Auditing (who had access when)

**Canonical membership doc**:
- `tenants/{tenantId}/users/{uid}`

Recommended fields:
- `role`: `owner | admin | operator | viewer`
- `status`: `active | invited | suspended`
- `created_at`
- `created_by_uid`

Optional mirror for UX:
- `users/{uid}/memberships/{tenantId}` (read-only mirror written by backend)

### 1.4 Account (broker / trading account)

An **Account** represents a broker account (e.g. Alpaca account) used for trading.

Enterprise requirements:
- A tenant can have **multiple accounts** (paper/live, multiple brokers, sub-accounts)
- An account can be **shared** across multiple users in a tenant (ops + traders)
- Risk policy is evaluated **per account** and **per tenant** (tenant-wide caps + account caps)

**Canonical account metadata**:
- `tenants/{tenantId}/accounts/{accountId}`

Recommended fields:
- `broker`: `alpaca` (future: `ibkr`, etc.)
- `environment`: `paper | live`
- `external_account_id` (broker-side ID)
- `status`: `active | disabled`
- `labels` (low-cardinality tags)
- `created_at`

**Account access**:
- `tenants/{tenantId}/accounts/{accountId}/access/{uid}` (optional fine-grained ACL)
  - If omitted, membership implies access.

**Credentials**:
- Stored in **Secret Manager**, not Firestore.
- Secret naming pattern (recommended):
  - `projects/{PROJECT_ID}/secrets/broker-{tenantId}-{accountId}/versions/latest`
  - Payload example:
    - `{ "key_id": "...", "secret_key": "...", "base_url": "..." }`

### 1.5 Strategy ownership

AgentTrader v2 supports three strategy ownership modes:

1) **Platform (global) strategies**
   - Owned by the platform; available via entitlements.
   - Examples: `gamma`, `whale`, `naive_flow_trend`

2) **Tenant-owned strategies**
   - Custom strategies (code or configuration) owned and governed by a single tenant.
   - Subject to tenant’s review workflow and change controls.

3) **User-owned strategies (optional, non-enterprise default)**
   - Personal experiments and sandbox strategies scoped to a user.
   - Enterprise mode typically disables this or requires tenant approval.

Ownership rules:
- **Execution always occurs under a tenant context**, even for user-owned strategies.
- Strategy configuration overrides are resolved in this order:
  1. Tenant strategy overrides
  2. Account strategy overrides (optional)
  3. Default strategy config

---

## 2) Auth context and request scoping

### 2.1 Tenant context

Every client request that touches tenant resources must have an **active tenant context**:

- Firebase Auth custom claims include:
  - `tenant_id` (or `tenantId` for back-compat; repo rules support both)
  - `role` (optional convenience; source of truth remains membership doc)

Firestore rules enforce:
- `request.auth.token.tenant_id == tenantId`
- membership exists at `tenants/{tenantId}/users/{request.auth.uid}`

This provides defense-in-depth:
- Client must present the correct tenant claim **and**
- Must be a member of that tenant in Firestore.

### 2.2 Multi-tenant users

If a user belongs to multiple tenants:
- The app sets the user’s **active tenant** by updating custom claims (admin SDK) and forcing token refresh.
- UI shows a tenant switcher sourced from `users/{uid}/memberships/*` (mirror) or via a backend API.

---

## 3) Firestore namespace layout (canonical)

### 3.1 Top-level collections

Recommended top-level collections:

- `tenants/{tenantId}/...` — primary enterprise boundary
- `users/{uid}/...` — identity + personal UX state
- `catalog/{doc}` — platform-owned registries (strategies, plan definitions)
- `ops/{doc}` — platform operational read models (already present)

### 3.2 Tenant subtree

#### Tenant identity and membership

- `tenants/{tenantId}`
- `tenants/{tenantId}/users/{uid}` — membership + role

#### Accounts

- `tenants/{tenantId}/accounts/{accountId}` — metadata
- `tenants/{tenantId}/accounts/{accountId}/snapshots/latest`
  - Latest broker snapshot (equity, buying_power, cash, status, updated_at)
- `tenants/{tenantId}/accounts/{accountId}/positions/{positionId}` (optional)
- `tenants/{tenantId}/accounts/{accountId}/orders/{orderId}` (optional)

#### Risk policy + state

- `tenants/{tenantId}/risk/policy`
  - Declarative limits (see section 5)
- `tenants/{tenantId}/risk/state`
  - Computed state (HWM, drawdown, breached flags, last evaluation time)
- `tenants/{tenantId}/risk/events/{eventId}`
  - Immutable audit trail of risk state transitions (breach, manual override, liquidation)

#### Strategy enablement

- `tenants/{tenantId}/strategy_entitlements/{strategyId}`
  - Whether a strategy is enabled for this tenant and optional plan metadata
- `tenants/{tenantId}/strategy_configs/{strategyId}`
  - Tenant override config (parameters, symbol allowlists, weights)
- `tenants/{tenantId}/strategy_runs/{runId}` (optional)
  - Execution metadata for audit and troubleshooting

#### Usage + quotas

- `tenants/{tenantId}/usage/{yyyymm}`
  - Aggregated counters (LLM calls, signals, orders, etc.)
- `tenants/{tenantId}/quota/policy`
  - Quota policy by plan (or references plan defaults)
- `tenants/{tenantId}/quota/state`
  - Current usage windows / limiter state (if using Firestore-based fallback)

#### Audit log (optional if using only Cloud Audit Logs)

- `tenants/{tenantId}/audit/{eventId}`
  - Application-level audit events (who changed what, when)

### 3.3 User subtree (enterprise minimal)

In enterprise mode, user subtree is **not** the primary boundary, but remains useful for:
- Personal preferences
- UI state
- Onboarding state
- Optional per-user “views” (denormalized read models)

Recommended:
- `users/{uid}` — profile
- `users/{uid}/memberships/{tenantId}` — membership mirror (read-only for clients)
- `users/{uid}/preferences/{doc}`

### 3.4 Compatibility with current implementation

The repo currently persists key trading artifacts under `users/{uid}/...`:

- Account snapshot variants:
  - `users/{uid}/data/snapshot`
  - `users/{uid}/alpacaAccounts/snapshot`
- Trades/signals:
  - `users/{uid}/shadowTradeHistory/{tradeId}`
  - `users/{uid}/signals/{signalId}` (and/or `tradingSignals`)

**Enterprise target** is to treat these as **user views** derived from the tenant/account canonical stores:

- Canonical write path (enterprise): `tenants/{tenantId}/accounts/{accountId}/...`
- Optional denormalized views (for UX): `users/{uid}/...` populated by backend materializers

This preserves:
- Existing frontend UX patterns
- Existing per-user listener efficiency
while enabling:
- Shared accounts
- Tenant-wide policy enforcement
- Central audit and billing

---

## 4) Isolation guarantees

### 4.1 Data isolation (Firestore)

**Guarantee**: A user can only read/write tenant data for tenants they belong to and have selected as active.

Mechanisms:
- **Firestore rules** gate tenant reads/writes to:
  - correct `tenant_id` claim AND membership doc exists
- **Path isolation**: tenant data lives under `tenants/{tenantId}/...`
- **Client SDK cannot mutate protected docs** (e.g., risk state, account snapshots, ledgers) where required

Important nuance:
- Server workloads using Admin SDK bypass rules, so server code must enforce tenant scoping at application level.

### 4.2 Secrets isolation

**Guarantee**: Client never sees broker credentials; access is limited to trusted service accounts.

Mechanisms:
- Secret Manager per tenant/account secrets
- IAM bindings grant `secretAccessor` only to:
  - account sync workload
  - execution engine workload
- Audit logs enabled for Secret Manager access

### 4.3 Compute isolation

Shared runtime is acceptable if:
- Every job is scoped by `(tenantId, accountId)` context
- All emitted events/logs carry `tenant_id` labels
- Backpressure and quotas prevent noisy-neighbor impact

For stricter enterprise tiers:
- **Tier A (shared)**: shared project, shared Firestore, strict logical isolation
- **Tier B (dedicated database)**: separate Firestore database per tenant (or per cohort)
- **Tier C (dedicated project)**: tenant-specific GCP project/VPC, isolated secrets, isolated CI/CD

### 4.4 Observability isolation

Requirements:
- Structured logs include `tenant_id`, `account_id`, `strategy_id`, `run_id`
- Metrics tagged by `tenant_id` (low cardinality: consider per-tenant metrics only for enterprise tier)
- Per-tenant dashboards and alert routing

---

## 5) Quota enforcement

Firestore rules cannot reliably enforce rate/usage quotas. Quotas must be enforced in **backend services**.

### 5.1 What to quota (recommended)

- **LLM usage**: requests/day, tokens/day, cost/day
- **Signal generation**: calls/minute, calls/day
- **Orders** (live trading): orders/minute, orders/day
- **Market data fanout**: subscriptions, symbols watched
- **Background workloads**: account sync frequency, P&L update frequency

### 5.2 Enforcement design (recommended)

**Primary control plane**: a backend “Quota Service” used by:
- Cloud Functions (callable endpoints)
- Strategy Engine
- Execution Engine
- Consumer/materializer services

Mechanisms (preferred order):

1) **Distributed limiter** (recommended): Redis / Memorystore token bucket per tenant (and optionally per account)
   - Keys: `quota:{tenantId}:{dimension}:{window}`
   - Atomic increments/leases; low latency

2) **Work-queue shaping**: Cloud Tasks queues segmented by tenant plan
   - Per-queue max dispatches / rate limits
   - Ensures noisy tenants cannot starve others

3) **Firestore transactional counters** (fallback only)
   - `tenants/{tenantId}/usage/{yyyymm}` updated via transactions
   - Beware hotspots at high QPS; suitable for low/moderate call rates

### 5.3 Fail-closed behavior

If quota checks fail (limiter unavailable), enterprise-safe behavior is:
- **Reject** non-essential user-initiated operations (signal generation, strategy changes)
- Continue essential safety operations (risk evaluation, kill-switch propagation)

### 5.4 Quota policy storage

Store plan defaults centrally:
- `catalog/plans/{planId}`

Override per tenant:
- `tenants/{tenantId}/quota/policy`

Record usage aggregates:
- `tenants/{tenantId}/usage/{yyyymm}`

---

## 6) Per-tenant risk limits

Risk controls must exist at multiple layers:

- **Pre-trade**: before generating or accepting a signal/order
- **Post-trade / continuous**: monitor drawdown, exposures, concentration
- **Emergency**: liquidation + kill-switch

### 6.1 Risk policy model

**Risk policy document**: `tenants/{tenantId}/risk/policy`

Recommended schema (high signal, extensible):

- `trading_enabled`: boolean (tenant master switch)
- `drawdown`:
  - `max_drawdown_pct` (e.g. 0.05)
  - `min_equity_usd` (e.g. 1000)
- `daily_loss`:
  - `max_daily_loss_pct`
  - `reset_timezone` (e.g. `America/New_York`)
- `exposure`:
  - `max_gross_exposure_usd`
  - `max_net_exposure_usd`
  - `max_leverage` (if margin)
- `order_limits`:
  - `max_order_notional_usd`
  - `max_orders_per_minute`
  - `max_open_orders`
- `position_limits`:
  - `max_positions`
  - `max_position_notional_usd`
  - `max_position_pct_equity`
- `concentration`:
  - `per_symbol_max_pct_equity`
  - `symbol_allowlist` / `symbol_denylist`
  - `sector_max_pct_equity` (optional)
- `strategies`:
  - `max_active_strategies`
  - `strategy_denylist` (defense-in-depth)
- `updated_at`, `updated_by_uid`

### 6.2 Risk state model

**Risk state document**: `tenants/{tenantId}/risk/state`

Computed fields:
- `high_water_mark_usd` (store as string if using Decimal precision)
- `current_equity_usd` (string)
- `drawdown_pct` (number)
- `daily_pnl_usd` (string) and/or `daily_pnl_pct`
- `risk_state`: `normal | limited | halted`
- `reasons`: array of strings (bounded)
- `last_evaluated_at`
- `breached_at` (if halted)
- `manual_override`:
  - `enabled`: boolean
  - `reason`
  - `by_uid`
  - `at`

### 6.3 Enforcement points

Risk checks are applied at:

- **Signal generation** (Cloud Function / Strategy Engine):
  - If tenant trading disabled or risk_state is `halted` → return `flat/hold` and log reason

- **Order creation** (Execution Engine):
  - Enforce hard caps: max order notional, order rate, symbol allowlist/denylist, position caps
  - If violated → reject order, emit audit event to `tenants/{tenantId}/risk/events/*`

- **Scheduled monitoring** (existing `pulse()` pattern):
  - Update account snapshot
  - Update risk state (HWM/drawdown, daily loss)
  - Push kill-switch state to any dependent services/UI

### 6.4 Emergency liquidation (tenant-scoped)

Enterprise behavior:
- Liquidation executes against a specific `(tenantId, accountId)`
- Requires operator/admin role (and optional break-glass claim)
- Must be fully auditable:
  - who triggered, when, which account, results, broker response IDs

Write:
- `tenants/{tenantId}/risk/events/{eventId}`
- `tenants/{tenantId}/audit/{eventId}` (if using app-level audit)

---

## 7) Per-tenant strategy enablement

### 7.1 Global strategy registry

Platform strategies are registered under:
- `catalog/strategies/{strategyId}`

Fields:
- `strategy_id` (matches doc ID)
- `display_name`
- `description`
- `default_config` (bounded map)
- `required_features` (e.g. needs options data)
- `status`: `active | deprecated`
- `version` (semantic or git SHA pin)

### 7.2 Tenant entitlements

Tenant enablement lives under:
- `tenants/{tenantId}/strategy_entitlements/{strategyId}`

Fields:
- `enabled`: boolean
- `mode`: `shadow | paper | live` (allowed modes for this tenant)
- `max_allocation_pct_equity` (optional tenant cap per strategy)
- `config_overrides` (bounded map; prefer storing in `strategy_configs` if large)
- `updated_at`, `updated_by_uid`

### 7.3 Effective strategy set

For a given tenant/account run:

1) Load tenant entitlements where `enabled == true`
2) Join with `catalog/strategies/{strategyId}` to get defaults and status
3) Apply tenant overrides from `tenants/{tenantId}/strategy_configs/{strategyId}`
4) Optionally apply account-specific overrides
5) Filter by risk policy denylist/allowlist (defense-in-depth)

### 7.4 Change control (enterprise)

Recommended enterprise controls:
- Strategy enable/disable changes are:
  - role-gated (admin/operator)
  - audited
  - optionally require dual approval for live trading

---

## 8) Summary: guarantees and responsibilities

- **Tenant boundary** is `tenants/{tenantId}`; enforced by auth claim + membership.
- **Users** are identities; membership defines access; user doc is not the enterprise boundary.
- **Accounts** are tenant resources; credentials live in Secret Manager.
- **Strategies** are globally registered but tenant-enabled via entitlements + overrides.
- **Isolation** is defense-in-depth: Firestore rules + server-side scoping + secret IAM boundaries.
- **Quotas** are enforced in backend (Redis/Tasks/transactions), not via rules.
- **Risk limits** are tenant-scoped and enforced at signal generation + execution + continuous monitoring.

---

## Appendix A — Minimal example documents (illustrative)

### Tenant membership

`tenants/acme_capital/users/uid_123`:

```json
{
  "role": "admin",
  "status": "active",
  "created_at": "timestamp",
  "created_by_uid": "uid_owner"
}
```

### Tenant risk policy

`tenants/acme_capital/risk/policy`:

```json
{
  "trading_enabled": true,
  "drawdown": { "max_drawdown_pct": 0.05, "min_equity_usd": 1000 },
  "daily_loss": { "max_daily_loss_pct": 0.03, "reset_timezone": "America/New_York" },
  "order_limits": { "max_order_notional_usd": 25000, "max_orders_per_minute": 10, "max_open_orders": 25 },
  "position_limits": { "max_positions": 25, "max_position_pct_equity": 0.2 },
  "concentration": { "per_symbol_max_pct_equity": 0.15, "symbol_denylist": ["TSLA"] },
  "updated_at": "timestamp",
  "updated_by_uid": "uid_123"
}
```

### Strategy entitlement

`tenants/acme_capital/strategy_entitlements/gamma`:

```json
{
  "enabled": true,
  "mode": "shadow",
  "max_allocation_pct_equity": 0.2,
  "updated_at": "timestamp",
  "updated_by_uid": "uid_123"
}
```

