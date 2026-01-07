# Ops Calm

## Intent
Define operational calmness interfaces: incident states, degraded-mode behaviors, runbooks-as-data, and SLO/SLA signals to guide safe system posture.

## Non-goals (for this vNEXT skeleton)
- Starting HTTP servers or emitting metrics
- Integrating with existing observability stack
- Automating remediation

## Deliverables in this module
- `interfaces.py`: Contract-only placeholders (no runtime behavior).
- `__init__.py`: Empty package marker.

## Constraints
- No imports from existing live systems under `backend/`.
- No execution logic, side effects, network calls, or persistence.
