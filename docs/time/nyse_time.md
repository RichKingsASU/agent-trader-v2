## NYSE Time (Single Source of Truth)

AgentTrader v2 canonical time handling lives in:

- `backend/time/nyse_time.py`
- `backend/time/providers.py`

### Canonical storage rule

- **Always store timestamps internally as tz-aware UTC** (`datetime` with `tzinfo=UTC`).
- **Only convert to `America/New_York`** for:
  - **session-aware logic** (market open/close, `is_market_open`, etc.)
  - **candle bucketing** aligned to NYSE time boundaries
  - **UI/log labeling** where humans expect ET

### Why this exists (DST pitfalls)

Hard-coded offsets like `-5` / `-4` (EST/EDT) break around daylight savings transitions and holidays.
This module uses `zoneinfo` and (optionally) an exchange calendar so:

- DST transitions are handled correctly (ET offset changes automatically)
- session boundaries are consistent
- there’s **no duplicated timezone math** scattered across the codebase

### Usage examples

#### Parse provider timestamps → UTC (canonical)

```python
from backend.time.nyse_time import parse_ts
from backend.time.providers import normalize_alpaca_timestamp

dt_utc_1 = parse_ts("2025-01-02T14:30:00Z")     # -> aware UTC
dt_utc_2 = parse_ts(1704205800)                 # epoch seconds -> aware UTC
dt_utc_3 = parse_ts(1704205800000)              # epoch ms -> aware UTC

alpaca_utc = normalize_alpaca_timestamp("2025-01-02T14:30:00Z")
```

#### Convert UTC → NY time for labeling / session logic

```python
from backend.time.nyse_time import to_nyse

dt_ny = to_nyse(dt_utc_1)  # -> aware America/New_York
```

#### Session helpers

```python
from datetime import date
from backend.time.nyse_time import (
  is_trading_day, market_open_dt, market_close_dt, is_market_open, next_open, previous_close
)

d = date(2025, 1, 2)
if is_trading_day(d):
    open_ny = market_open_dt(d)
    close_ny = market_close_dt(d)

open_now = is_market_open(open_ny)  # accepts UTC or NY-aware datetimes
```

#### Candle bucketing

```python
from backend.time.nyse_time import floor_to_timeframe, ceil_to_timeframe

bar_start_ny = floor_to_timeframe(dt_utc_1, "5m", tz="America/New_York")
bar_end_ny = ceil_to_timeframe(dt_utc_1, "5m", tz="America/New_York")
```

### Exchange calendar support

If installed, `exchange-calendars` enables holiday/special-session awareness.

- Enable/disable via env: `USE_EXCHANGE_CALENDAR=true|false`
- If unavailable/disabled, the fallback is **weekday-only 09:30–16:00 ET** (does not account for holidays).

