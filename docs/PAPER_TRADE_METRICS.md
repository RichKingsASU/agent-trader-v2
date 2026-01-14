# Paper Trade Metrics (Inventory + Data Flow)

This doc inventories where paper-trade metrics come from today and how they flow through the system.

## Metrics inventory

### Realized P&L

- **Ledger-based (recommended canonical)**
  - **Definition**: FIFO realized P&L net of fees/slippage.
  - **Source**: `tenants/{tenant_id}/ledger_trades/{trade_id}` (fill-level, append-only).
  - **Computation**:
    - FIFO attribution (gross + fees + net): `backend/ledger/pnl.py::compute_pnl_fifo()`
    - Period attribution (delta of cumulative realized, plus unrealized at period end): `backend/ledger/strategy_performance.py::compute_strategy_pnl_for_period()`
  - **Notes**: fees and slippage are treated as fee-like costs and allocated FIFO into realized net P&L.

- **Shadow/paper execution (per-trade record)**
  - **Definition**: realized P&L when a shadow trade is closed.
  - **Source**: `users/{uid}/shadowTradeHistory/{shadow_id}`
  - **Fields**:
    - `final_pnl` (string) on close
    - `final_pnl_percent` (string) on close
  - **Notes**: this is per shadow-trade record, not (yet) aggregated into a canonical ledger.

### Unrealized P&L

- **Ledger-based**
  - **Definition**: mark-to-market P&L on open FIFO lots.
  - **Computation**: `backend/ledger/pnl.py::compute_fifo_pnl()` using `mark_prices`.

- **Shadow/paper execution**
  - **Definition**: current (unrealized) P&L for OPEN shadow trades.
  - **Source**: `users/{uid}/shadowTradeHistory/{shadow_id}`
  - **Fields**:
    - `current_pnl` (string)
    - `pnl_percent` (string)
    - `current_price` (string)

### Win rate

- **Ledger-based**
  - **Definition**: percent of closed position events with positive realized gross P&L.
  - **Computation**: `backend/analytics/trade_parser.py`
    - `compute_win_loss_ratio()` (overall)
    - `compute_daily_pnl()` (daily win rate)
  - **Implementation detail**: uses FIFO attribution to identify fills that close inventory (`closed_positions` in `compute_pnl_fifo`).

### Drawdown

- **Analytics drawdown (max drawdown %)**
  - **Definition**: max peak-to-trough drawdown on an equity curve derived from daily net P&L.
  - **Computation**: `backend/analytics/trade_parser.py` (`max_drawdown_pct` on `TradeAnalytics`).

- **Risk monitoring (drawdown velocity)**
  - **Definition**: rolling drawdown acceleration, used for safety monitoring.
  - **Computation**: `backend/risk/drawdown_velocity.py::compute_drawdown_velocity()`
  - **Notes**: this is a time-window “speed of drawdown” metric, not a full-period max drawdown.

## Data flow diagram

```mermaid
flowchart LR
  subgraph Strategy Service
    A[Signal / user action] --> B[/POST /trades/execute/]
    B -->|shadow mode ON| C[users/{uid}/shadowTradeHistory]
    B -->|shadow mode OFF| D[tenants/{tenant}/paper_orders]
  end

  subgraph Ledger
    E[tenants/{tenant}/ledger_trades (fills)]
    F[backend/ledger/pnl.py FIFO attribution]
    G[backend/ledger/strategy_performance.py period attribution]
  end

  subgraph Analytics API
    H[/GET /api/analytics/trade-analytics/]
    I[backend/analytics/trade_parser.py daily P&L + win rate + max drawdown]
  end

  D -. (future: promote to ledger fills) .-> E
  C -. (future: promote to ledger fills) .-> E

  E --> F --> G
  E --> I
  I --> H
```

