# Attribution

## Intent
Define interfaces for performance and decision attribution (signal -> action -> outcome) including standardized event schemas and explainability artifacts.

## Non-goals (for this vNEXT skeleton)
- Computing production PnL or official accounting
- Replacing existing ledger/analytics modules
- Building dashboards or APIs

## Deliverables in this module
- `interfaces.py`: Contract-only placeholders (no runtime behavior).
- `__init__.py`: Empty package marker.

## Constraints
- No imports from existing live systems under `backend/`.
- No execution logic, side effects, network calls, or persistence.
