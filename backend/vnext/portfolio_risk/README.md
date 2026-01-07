# Portfolio Risk

## Intent
Define portfolio-level risk representation and interfaces (exposures, Greeks, concentration, liquidity) as consumable artifacts for vNEXT governance and attribution.

## Non-goals (for this vNEXT skeleton)
- Connecting to broker accounts
- Calculating real Greeks from live option chains
- Replacing existing `backend/risk*` services

## Deliverables in this module
- `interfaces.py`: Contract-only placeholders (no runtime behavior).
- `__init__.py`: Empty package marker.

## Constraints
- No imports from existing live systems under `backend/`.
- No execution logic, side effects, network calls, or persistence.
