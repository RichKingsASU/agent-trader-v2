# News Intelligence

## Intent
Define the vNEXT boundary for extracting structured, tradable attributes from news (entities, sentiment, topics, novelty) and providing them as neutral artifacts.

## Non-goals (for this vNEXT skeleton)
- Calling external news APIs
- LLM/provider integration
- Replacing existing `backend/news_*` implementations

## Deliverables in this module
- `interfaces.py`: Contract-only placeholders (no runtime behavior).
- `__init__.py`: Empty package marker.

## Constraints
- No imports from existing live systems under `backend/`.
- No execution logic, side effects, network calls, or persistence.
