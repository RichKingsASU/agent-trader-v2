## Data Freshness Contract (Market Data)

### Purpose
Strategies must **refuse to evaluate** when the market data they depend on is stale. This prevents “trading on yesterday’s tape” during ingest outages, DB lag, or upstream feed degradation.

### Definition
**Freshness is derived from the latest market-data event timestamp** available to the strategy at evaluation time:

- **Bars**: latest bar timestamp (bar close time) for the symbol and timeframe being used
- **Ticks/quotes** (if used by a strategy): latest tick/quote timestamp

If freshness cannot be determined (missing timestamp), the system must **fail closed** and treat the data as **STALE**.

### Policy (default)
For bar-based strategies:

- **Stale threshold**: \(2 \times\) the bar interval (example: 1m bars → 120s threshold)

Callers may override policy per-service via environment configuration (implementation-defined), but must not silently treat unknown timestamps as fresh.

### Enforcement behavior
When data is stale:

- **Strategy evaluation returns NOOP** (no signal, no proposal, no broker interaction)
- A structured log is emitted with **`intent_type="STALE_DATA"`** and details including:
  - symbol, strategy name/id (if available)
  - latest market timestamp (UTC)
  - current time (UTC)
  - computed age in seconds
  - threshold in seconds
  - source (e.g., `bars:market_data_1m`)

### Implementation notes
The shared helper lives in:

- `backend/common/freshness.py`

It is pure (no IO) and returns a structured `FreshnessCheck` result so call sites can:

- log consistently
- return NOOP consistently
- remain testable without DB/broker dependencies

