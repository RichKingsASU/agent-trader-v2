# Paper Trade Metrics (Shadow Mode)

This document inventories **paper trading metrics** (Shadow Mode) and shows the **data flow** that produces them.

## Metrics inventory

### Trade-level (per shadow trade)

**Storage location**: Firestore `users/{uid}/shadowTradeHistory/{shadow_id}`

- **Unrealized P&L (USD)**: `current_pnl` (string, cents)
  - **Meaning**: mark-to-market P&L for `status == "OPEN"`
  - **How computed**: entry price vs current price using `Decimal` math
- **Unrealized P&L (%)**: `pnl_percent` (string, 0.01%)
  - **Meaning**: \(pnl / (|entry\_price \times quantity|) \times 100\)
- **Realized P&L (USD)**: `realized_pnl` (string, cents) + back-compat `final_pnl`
  - **Meaning**: entry→exit P&L for `status == "CLOSED"`
  - **How computed**: on close, recalculated from `entry_price`, `quantity`, `side`, and `exit_price` (does **not** depend on stale `current_pnl`)
- **Realized P&L (%)**: `realized_pnl_percent` (string, 0.01%) + back-compat `final_pnl_percent`
- **Win flag**: `is_win` (bool)
  - **Meaning**: `True` iff realized P&L \(>\) 0

**Primary code paths**
- Create shadow trade: `backend/strategy_service/routers/trades.py` → `create_shadow_trade()`
- Close shadow trade (realized P&L): `backend/strategy_service/routers/trades.py` → `close_shadow_trade()`
- Core Decimal math: `backend/strategy_service/shadow_metrics.py` → `compute_trade_pnl()`

### Aggregate (per user)

**API location**: `GET /trades/shadow/metrics` (Strategy Service)

**Computed metrics**
- **Realized P&L (USD)**: sum of CLOSED trades (`realized_pnl` / `final_pnl`)
- **Unrealized P&L (USD)**: sum of OPEN trades, marked-to-market using `live_quotes/{symbol}` (fallback: stored `current_pnl`)
- **Net P&L (USD)**: realized + unrealized
- **Win rate (%)**: wins / closed_trades × 100
- **Max drawdown (USD, %)**:
  - Computed on the **cumulative realized P&L curve** (starts at 0)
  - Drawdown is peak-to-trough (negative values), returned as:
    - `max_drawdown_usd`
    - `max_drawdown_percent`

**Primary code paths**
- Endpoint: `backend/strategy_service/routers/trades.py` → `get_shadow_trade_metrics()`
- Aggregation logic: `backend/strategy_service/shadow_metrics.py` → `compute_shadow_metrics()`, `compute_max_drawdown_from_realized_pnls()`

## Decimal usage validation

### What is Decimal-safe now

- **P&L math** uses `Decimal` end-to-end:
  - `compute_trade_pnl()` (entry/current/qty/side → pnl_usd + pnl_percent)
  - close path recalculates realized P&L using the same `Decimal` function
- **Persisted money fields** in shadow trades are **strings** (e.g. `"10.00"`) to avoid float drift.

### Remaining float exposure (expected/compat)

- Incoming API requests may still originate as floats in clients, but the request model now parses `notional` as `Decimal` and converts to float **only** when writing paper orders (`paper_orders`) that currently store notional as a number.

## Data flow diagram

```mermaid
flowchart TD
  A[Client / Strategy] -->|POST /trades/execute| B[Strategy Service: execute_trade]
  B --> C{Shadow mode enabled?}
  C -->|Yes| D[create_shadow_trade]
  D -->|read| Q[live_quotes/{symbol}]
  D -->|write| S[users/{uid}/shadowTradeHistory/{shadow_id}\nstatus=OPEN\nentry_price, quantity\ncurrent_pnl=\"0.00\"]
  C -->|No| P[paper_orders insert (simulated/live path)]

  S -->|GET /trades/shadow/metrics| M[Metrics endpoint]
  M -->|read OPEN+CLOSED trades| S
  M -->|read marks| Q
  M -->|compute via Decimal| X[compute_shadow_metrics\nrealized/unrealized\nwin_rate\nmax_drawdown]
  X --> R[JSON metrics response]

  S -->|POST /trades/close-shadow| Z[close_shadow_trade]
  Z -->|read| Q
  Z -->|compute realized via Decimal| Y[compute_trade_pnl]
  Z -->|update| S2[shadowTradeHistory doc\nstatus=CLOSED\nexit_price\nrealized_pnl + is_win]
```

## Tests

- Unit tests (Decimal correctness + aggregation):
  - `tests/test_shadow_trade_metrics.py`

