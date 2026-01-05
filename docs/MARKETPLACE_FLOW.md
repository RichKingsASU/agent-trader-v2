# Marketplace flow (ledger → performance → fees) + tenancy isolation

This repo’s marketplace/performance-fee system is designed around a **tenant-scoped, immutable ledger** and **deterministic monthly snapshots**.

This doc describes the **current** implementation and the invariants it relies on.

---

## Data model (where data lives)

- **Fill-level trade ledger (source of truth)**:
  - Path: `tenants/{tenant_id}/ledger_trades/{trade_id}`
  - Shape: fill-equivalent events (one document per fill)
  - Key fields (current): `tenant_id`, `uid`, `strategy_id`, `symbol`, `side`, `qty`, `price`, `ts`, `fees`, `slippage`
  - Writer: execution engine writes append-only via Firestore `create()` (immutability).

- **Monthly per-user strategy performance snapshot**:
  - Path: `tenants/{tenant_id}/strategy_performance/{perf_id}`
  - Deterministic id: `{uid}__{strategy_id}__YYYY-MM`
  - Computed from the fill ledger using FIFO matching.

---

## End-to-end flow

### 1) Strategy execution writes the ledger (append-only)

- When a broker reports a fill, the execution engine writes a ledger doc to:
  - `tenants/{tenant_id}/ledger_trades/{trade_id}`
- The write uses Firestore `create()` to enforce **append-only** semantics.
- The ledger is intentionally **immutable**: downstream computations can be recomputed idempotently.

### 2) Monthly snapshot calculation (FIFO attribution)

The monthly snapshot is computed as follows (for a specific `tenant_id`, month `[start, end)`):

- Read all ledger fills with `ts < period_end` (needed to correctly attribute closes that were opened earlier).
- Compute FIFO attribution per `(tenant_id, uid, strategy_id)`:
  - **Gross realized P&L**: computed from matched lots ignoring fees.
  - **Realized fees**: fees+slippage are allocated FIFO per matched quantity (opening + closing fees).
  - **Net realized P&L**: gross realized P&L minus realized fees.
  - **Unrealized P&L**: mark-to-market at `period_end` (using an effective cost basis that embeds fees+slippage).

Implementation notes:
- The period is treated as **\[period_start, period_end)** (end-exclusive).
- Realized attribution is computed as a **delta of cumulative realized**:
  - `realized_in_period = realized(as_of=period_end) - realized(as_of=period_start)`
- The snapshot script writes a single deterministic doc per (uid, strategy, month).

### 3) Fee basis fields in `strategy_performance`

The snapshot writer currently writes both marketplace-compatible fields and debugging fields:

- **Marketplace-compatible (fee computation inputs)**:
  - `trade_count`: count of fills with `ts ∈ [period_start, period_end)`
  - `realized_pnl`: **gross** realized P&L (before fees/slippage)
  - `fees`: realized fees+slippage allocated via FIFO
  - `net_profit`: `realized_pnl - fees`

- **Additional attribution fields (ops/debug)**:
  - `realized_pnl_net`: net realized P&L for the period
  - `unrealized_pnl`: unrealized P&L as-of `period_end` (net-of-fees-in-basis)

### 4) Performance fee / revenue share (term-based)

This repo includes a generic fee calculator (`backend/marketplace/performance.py`) that supports:

- `fee_basis = net_profit_positive` (default): charge only on positive net profit
- `fee_basis = net_profit`: charge on net profit even if negative (not typical)
- `revenue_share_bps`: fee rate in basis points (0..10000)

Important:
- Term/subscription resolution and invoicing are **tenant-scoped** and may be handled by a separate billing service.
- The snapshot fields above (`net_profit`, etc.) are the canonical inputs for that fee computation.

---

## Tenant isolation / “no cross-user leakage”

### Tenant isolation

All operational marketplace data is stored under:

- `tenants/{tenant_id}/...`

This provides a hard namespacing boundary:

- Ledger reads for performance snapshots are performed only against
  - `tenants/{tenant_id}/ledger_trades`
- Snapshot writes land only under
  - `tenants/{tenant_id}/strategy_performance`

### Cross-user isolation within a tenant

Within a tenant, snapshots are **keyed by uid**:

- Document id: `{uid}__{strategy_id}__YYYY-MM`
- Document fields include `uid` and `strategy_id`.

That means:

- A snapshot is always attributable to exactly one `(uid, strategy_id, month)` tuple.
- Any end-user API that serves snapshots must filter by `uid == requester.uid` (and should also validate tenant context).

Guardrails in tests:
- The repo includes tenancy guard tests that prohibit common “global collection access” patterns in service code (not a substitute for Firestore rules, but a useful backstop).

---

## Operational checklist (correctness invariants)

- **Immutability**: `ledger_trades` must be append-only; never mutate fills in-place.
- **Determinism**: FIFO ordering must be stable in timestamp ties (use fill/order identifiers as tie-breakers).
- **Period semantics**: use `[start, end)` consistently; avoid double-counting at boundaries.
- **Fee attribution**: treat `fees` and `slippage` as positive costs; allocate opening+closing costs to realized P&L when lots close.
- **Tenancy**: all reads/writes must be under `tenants/{tenant_id}`; never query tenant-owned collections at top-level.

