# Market Regime

## Intent
Define interfaces and data shapes for detecting and tracking market regimes (trend, chop, volatility states) and exposing regime annotations to downstream vNEXT modules.

## Non-goals (for this vNEXT skeleton)
- Selecting a specific regime model/algorithm
- Online inference wired into production loops
- Backfilling or migrating existing regime logic

## Deliverables in this module
- `interfaces.py`: Contract-only placeholders (no runtime behavior).
- `__init__.py`: Empty package marker.

## Constraints
- No imports from existing live systems under `backend/`.
- No execution logic, side effects, network calls, or persistence.
