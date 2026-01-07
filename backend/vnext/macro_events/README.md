# Macro & Event Calendar (Contracts Only)

This directory defines **read-only contracts** for macro-economic and market
events (e.g., CPI, FOMC, earnings, holidays) via dataclasses and a provider
interface.

## Safety & Scope

- **Read-only**: This package contains **interfaces only** (no fetching, no I/O,
  no calendar implementation).
- **Never triggers trades**: Nothing here should be used as an entry/exit signal
  or to place orders.
- **Risk modifier only**: The only intended use is to **modify risk controls**,
  such as:
  - tightening max exposure / leverage
  - reducing position sizing
  - widening circuit-breakers / gating
  - adding extra guards around known high-volatility windows

## Primary Contract

See `interfaces.py` for:

- `MacroEvent`: immutable event record
- `EventSeverity`: comparable severity ranking
- `EventWindow`: risk-relevant time window
- `MacroEventProvider.get_active_events(now, lookahead_minutes)`: read-only query
  for events relevant to the current time horizon

