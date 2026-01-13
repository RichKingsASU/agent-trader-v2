# Confidence Signal Agent (Paper Trading)

## Goal
Give the operator immediate clarity during **paper trading / shadow mode**:

- open positions
- unrealized P&L
- daily P&L
- drawdown %

Refresh target: **< 5s**.

## Data sources (authoritative)

- **Open positions (paper)**: Firestore user-scoped shadow trades  
  - Path: `users/{uid}/shadowTradeHistory/*`  
  - A position is considered **open** when `status == "OPEN"`.
  - Writer: `backend/strategy_service/routers/trades.py` (`create_shadow_trade`)

- **Pricing / fast refresh (<5s)**: Firestore tenant-scoped live quotes  
  - Collection: `tenants/{tenantId}/live_quotes/*`  
  - Reader: `frontend/src/hooks/useMarketLiveQuotes.ts`
  - Used to compute mark price (mid if bid/ask available; else last/price).

- **Daily base equity anchor** (for “synthetic equity” + drawdown): Firestore warm-cache broker snapshot  
  - Doc: `users/{uid}/alpacaAccounts/snapshot`  
  - Writer: `backend/brokers/alpaca/account_sync.py`  
  - Reader: `frontend/src/hooks/useAlpacaAccountSnapshot.ts`

## Computations

- **Unrealized P&L**: recomputed client-side for each open position using live quotes:
  - BUY: \((mark - entry) \times qty\)
  - SELL: \((entry - mark) \times qty\)

- **Daily P&L**:
  - \(daily\_pnl = realized\_today + unrealized\_open\)
  - `realized_today` sums `final_pnl` for shadow trades with `status=="CLOSED"` and `closed_at_iso` matching today (UTC date).

- **Drawdown %** (operator-facing):
  - Uses a per-day **high-watermark (HWM)** of synthetic equity.
  - `base_equity_usd` is persisted once per day in browser `localStorage`.
  - \(drawdown\% = (HWM - current) / HWM \times 100\)

## UI output (operator)

- Component: `frontend/src/components/ConfidenceSignalPanel.tsx`
  - Shows:
    - **Open positions**
    - **Unrealized P&L**
    - **Daily P&L**
    - **Drawdown %**
  - Shows quote freshness (**LIVE/STALE/OFFLINE**) and last update timestamp.

- Placement:
  - `frontend/src/pages/Index.tsx` right sidebar (“Paper Trading” section)

