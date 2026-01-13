# P&L Attribution (Firestore Trade Ledger)

This repo implements a **Firestore-only**, **tenant-scoped**, **append-only** trade ledger that can compute:

- realized P&L
- unrealized P&L
- strategy attribution per user
- performance-fee basis for a strategy marketplace

## Collections (all tenant-scoped)

All data is scoped under a tenant document:

- `tenants/{tid}/accounts/{account_id}`
- `tenants/{tid}/strategies/{strategy_id}`
- `tenants/{tid}/runs/{run_id}`
- `tenants/{tid}/ledger_trades/{trade_id}` (**append-only**)

### `tenants/{tid}/accounts/{account_id}`

Suggested fields (example; keep small):

- **`tenant_id`**: `string`
- **`account_id`**: `string` (redundant, should match doc id)
- **`uid`**: `string` (owner)
- **`broker`**: `string` (e.g. `alpaca`)
- **`external_account_id`**: `string`
- **`base_ccy`**: `string` (e.g. `USD`)
- **`created_at`**: `timestamp`
- **`status`**: `string` (`active`/`disabled`)

### `tenants/{tid}/strategies/{strategy_id}`

- **`tenant_id`**: `string`
- **`strategy_id`**: `string` (redundant, should match doc id)
- **`name`**: `string`
- **`created_by_uid`**: `string`
- **`version`**: `string` (optional)
- **`status`**: `string` (`active`/`disabled`)
- **`performance_fee_bps`**: `number` (optional; for marketplace)
- **`created_at`**: `timestamp`

### `tenants/{tid}/runs/{run_id}`

A “run” is a concrete execution window for a strategy (e.g. one live session or one backtest job).

- **`tenant_id`**: `string`
- **`run_id`**: `string` (redundant, should match doc id)
- **`strategy_id`**: `string`
- **`uid`**: `string` (user running / responsible for the run)
- **`started_at`**: `timestamp`
- **`ended_at`**: `timestamp|null`
- **`status`**: `string` (`running`/`stopped`/`failed`)

## Append-only ledger: `tenants/{tid}/ledger_trades/{trade_id}`

One document per **fill** (or fill-equivalent). Documents are **immutable**: writers must only append and must not update existing fills.

In code we enforce append-only semantics by using Firestore `create()` (fails if the document exists).

### Schema (required fields)

- **`tenant_id`**: `string`
- **`uid`**: `string` (who owns the position/P&L)
- **`strategy_id`**: `string`
- **`run_id`**: `string`
- **`symbol`**: `string` (normalized uppercase)
- **`side`**: `string` (`buy`/`sell`)
- **`qty`**: `number` (positive; direction via `side`)
- **`price`**: `number` (fill price, > 0)
- **`ts`**: `timestamp` (fill timestamp)

### Schema (recommended fields)

- **`order_id`**: `string|null` (client/broker order id)
- **`broker_fill_id`**: `string|null` (idempotency key if available)
- **`fees`**: `number` (>= 0, USD cost estimate)
- **`slippage`**: `number` (>= 0, USD cost estimate)
- **`account_id`**: `string|null` (tenant account)
- **`created_at`**: `timestamp` (writer timestamp)

### Example ledger trade document

```json
{
  "tenant_id": "t1",
  "uid": "u1",
  "strategy_id": "s1",
  "run_id": "r1",
  "symbol": "AAPL",
  "side": "buy",
  "qty": 10,
  "price": 100.0,
  "ts": "2025-01-01T09:30:00Z (Firestore Timestamp)",
  "order_id": "ord-123",
  "broker_fill_id": "fill-abc",
  "fees": 1.0,
  "slippage": 0.0,
  "account_id": "acct-1",
  "created_at": "2025-01-01T09:30:00Z (Firestore Timestamp)"
}
```

## P&L model

### Cost basis method: FIFO

This implementation uses **FIFO (first-in-first-out)** lots per `(tenant_id, uid, strategy_id, symbol)`.

- **Realized P&L**: generated when a trade closes existing lots.
- **Unrealized P&L**: mark-to-market of remaining open lots using an external mark price per symbol.

### Fees + slippage handling

`fees + slippage` are treated as **execution costs** and distributed across quantity as a per-unit price adjustment:

- BUY effective price: \( p_\text{eff} = p + \frac{\text{fees} + \text{slippage}}{q} \)
- SELL effective price: \( p_\text{eff} = p - \frac{\text{fees} + \text{slippage}}{q} \)

This makes the costs automatically flow into realized/unrealized P&L in a consistent way.

## Options: premium + 100x contract multiplier

Options fills are typically quoted as **premium per underlying share**, while the position size is in **contracts**.
US equity/index options are usually **100 shares per contract**, so P&L must be multiplied by **100**.

In code we support this by carrying a `multiplier` on `LedgerTrade` (default `1.0`), and we **infer**
`multiplier=100` when:

- `asset_class == "OPTIONS"`, or
- the symbol looks like an OCC-style contract symbol (e.g. `SPY251230C00500000`)

This ensures:

- **premium paid/received** is correctly reflected in cost basis (opening lots)
- **realized close** P&L is correct when closing lots (sell-to-close / buy-to-cover)
- **unrealized MTM** scales correctly by contract size

### Quick realized example (long call)

BUY 1 `SPY251230C00500000` @ 1.00, fees=1.00  
SELL 1 `SPY251230C00500000` @ 1.50, fees=1.00

- Effective buy: \( 1.00 + \frac{1}{1 \times 100} = 1.01 \)
- Effective sell: \( 1.50 - \frac{1}{1 \times 100} = 1.49 \)
- **Realized P&L**: \( (1.49 - 1.01) \times 1 \times 100 = 48.00 \)

## Options MTM greek attribution (delta/gamma/vega/theta + residual)

For explainability, we provide a deterministic decomposition of **observed option price changes**
into greek-style components using two snapshots (start/end):

- Total MTM: \( \Delta P \times q \times m \)
- Delta: \( \Delta \times \Delta S \times q \times m \)
- Gamma: \( \frac{1}{2}\Gamma (\Delta S)^2 \times q \times m \)
- Vega: \( \nu \times \Delta IV \times q \times m \)
- Theta: \( \Theta \times \Delta t_\text{days} \times q \times m \)
- Residual: Total - (Delta+Gamma+Vega+Theta)

Code pointer: `backend/ledger/options_attribution.py`

## Worked example (deterministic)

Tenant `t1`, user `u1`, strategy `s1`, run `r1`, symbol `AAPL`:

1) BUY 10 @ 100.00, fees=1.00  
   - effective buy = 100.10
2) BUY 5 @ 110.00, fees=0.50  
   - effective buy = 110.10
3) SELL 8 @ 120.00, fees=0.80  
   - effective sell = 119.90  
   - closes 8 from the first lot (100.10)

Realized P&L after step 3:

- \( (119.90 - 100.10) \times 8 = 158.40 \)

Remaining position:

- 2 shares @ 100.10 (FIFO remainder)
- 5 shares @ 110.10

If mark price is `AAPL=125.00`, unrealized P&L:

- \( (125.00 - 100.10) \times 2 = 49.80 \)
- \( (125.00 - 110.10) \times 5 = 74.50 \)
- total unrealized = **124.30**

Total net P&L = realized + unrealized = **282.70**

## Strategy attribution + performance fee basis

Because each ledger entry includes both `uid` and `strategy_id`, you can aggregate computed P&L by:

- user (`uid`)
- strategy (`strategy_id`)
- user+strategy (`uid`, `strategy_id`) (recommended for a marketplace)

Suggested **performance fee basis** (marketplace default):

- **`performance_fee_basis = realized_pnl`** per `(tenant_id, uid, strategy_id)` over the fee period

Rationale: charging fees on realized results avoids charging on transient mark-to-market changes.

## Code pointers

- P&L engine (pure Python): `backend/ledger/pnl.py`
- Ledger trade shape: `backend/ledger/models.py`
- Firestore append-only helper: `backend/ledger/firestore.py`

