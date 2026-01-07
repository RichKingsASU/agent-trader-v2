# Macro Events

## Intent
Define the vNEXT boundary for representing, ingesting, and reasoning over macroeconomic and event-driven catalysts (e.g., CPI, FOMC, earnings calendars) as structured signals.

## Non-goals (for this vNEXT skeleton)
- Fetching/ingesting live macro feeds
- Publishing signals into production execution paths
- Coupling to current `backend/*` runtime services

## Deliverables in this module
- `interfaces.py`: Contract-only placeholders (no runtime behavior).
- `__init__.py`: Empty package marker.

## Constraints
- No imports from existing live systems under `backend/`.
- No execution logic, side effects, network calls, or persistence.
