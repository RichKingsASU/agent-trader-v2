# Regime Modifier Contract (Macro / Event + GEX)

## Purpose
The **Macro / Event** and **GEX** components are **regime modifiers**: they publish *risk/threshold context* for downstream strategies. They **must not** produce trade-direction outputs.

Downstream strategies remain responsible for:
- trade direction (long/short selection),
- entry/exit logic,
- order construction and execution gating.

## Macro Inputs (Sources)

### Macro / Event inputs (economic + news)
- **Economic releases**: FRED observations (e.g., CPI, GDP, unemployment, PCE, NFP) via `functions/utils/macro_scraper.py`
- **Event/news context**: Alpaca News API (macro-relevant headlines) via `functions/utils/macro_scraper.py`
- **FOMC**: tracked as a configured event key (`FOMC`) in `MAJOR_ECONOMIC_EVENTS` (data sourcing depends on available feeds; used for detection/labeling)

### Options microstructure input (GEX)
- **Option chain snapshots**: Alpaca options snapshots via `functions/utils/gex_calculator.py`
- Derived indicators include **net GEX**, **zero-gamma** levels, and volatility bias labels.

## Output (Single Downstream Interface)

### Firestore document
All regime context is written to:
- **`systemStatus/market_regime`**

This is the **only** supported integration point for downstream strategies.

### Contract fields (stable keys)
- **GEX block** (per underlying, e.g. `spy`, `qqq`)
  - `spy.net_gex` (number or numeric string; downstream should parse safely)
  - Additional fields may exist (e.g., spot price, bias labels)
- **Macro/Event block**
  - `macro_event_detected`: boolean
  - `macro_event_status`: one of
    - `Normal`, `Volatility_Event`, `High_Volatility`, `Extreme_Volatility`
  - `stop_loss_multiplier`: float (>= 1.0)
  - `position_size_multiplier`: float (<= 1.0)
  - `macro_events[]`: list of event summaries
    - `event_name` (e.g., `CPI`, `FOMC`)
    - `surprise_magnitude`
    - `volatility_expectation`: `low|medium|high|extreme`
    - `recommended_action`: **allowlist only**
      - `widen_stops|tighten_stops|reduce_size|pause_trading|normal`
    - `confidence`
    - `reasoning` (human text; do not machine-parse for decisions)

## Regime Influence Map (What changes downstream)

### 1) GEX → threshold modulation (example pattern)
- **net GEX < 0 (short gamma)**:
  - tighten hedging thresholds
  - reduce frequency caps between hedges
  - lower max notional / allocation ceilings
- **net GEX > 0 (long gamma)**:
  - baseline thresholds
  - normal sizing ceilings

### 2) Macro/Event → risk posture (no direction)
- `macro_event_detected = true`:
  - widen stops by `stop_loss_multiplier`
  - shrink position size by `position_size_multiplier`
  - optionally **pause trading** when `recommended_action == pause_trading`

### 3) Combined behavior (safe default precedence)
- If `recommended_action == pause_trading`: **HOLD** / do not open new risk
- Else apply multipliers to:
  - stop widths
  - sizing
  - threshold tuning

## Safety Guarantees

### Hard guarantees (enforced in code)
- The Macro/Event layer **cannot emit BUY/SELL** or other trade-direction actions:
  - LLM outputs are sanitized to a strict `recommended_action` allowlist.
  - Directional advisory fields (e.g., `market_impact`) are **not persisted** to `systemStatus/market_regime`.
- The published contract is **risk/threshold-only** (multipliers + regime state).

### Soft guarantees (integration rules)
- Downstream strategies **must not** treat any macro fields as directional alpha.
- `reasoning` is for **human audit only** and must not be parsed into actions.

## Integration Readiness Checklist (Downstream Strategy)
- Read `systemStatus/market_regime` with a cache (e.g., 60s TTL).
- If `macro_event_detected` and `recommended_action == pause_trading`:
  - return **HOLD** / no-new-orders
- Otherwise:
  - multiply stop widths by `stop_loss_multiplier`
  - multiply sizing by `position_size_multiplier`
  - optionally adjust thresholds when `net_gex < 0`
- Log the applied modifiers for auditability.

