# Market Open Safety (Trade Blocking)

To avoid unstable conditions right after the NYSE open, the execution engine applies a **market-open cooldown** for **equities**.

## Default delay

- **15 minutes** after the NYSE market open.
- During this window, `RiskManager.validate()` rejects equity order intents with reason `market_open_trade_block`.

## Override mechanism (env vars)

You can override/disable the cooldown via environment variables:

- **Disable by setting minutes to zero**:
  - `EXEC_MARKET_OPEN_TRADE_BLOCK_MINUTES=0`
- **Force-disable via a boolean flag**:
  - `EXEC_MARKET_OPEN_TRADE_BLOCK_DISABLED=1`

Notes:

- This guard currently applies to `asset_class=EQUITY` only.
- The open time is computed in `America/New_York` using `backend/time/nyse_time.py` (calendar-aware if `exchange_calendars` is available; otherwise weekday-only 09:30–16:00 fallback).

