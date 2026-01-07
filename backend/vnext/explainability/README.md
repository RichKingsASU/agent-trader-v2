# vNEXT Explainability (Narrative Schema)

This package defines **data-only narrative explanations** for decisions.

## Promotion requirement

**Explainability is mandatory for promotion.**

Any decision artifact that is promoted beyond purely observational workflows must have a `DecisionNarrative` available that includes:
- a short human-readable summary
- a concrete list of contributing factors with evidence references
- an explicit confidence statement (including uncertainties)

## Deterministic-first policy

- **Deterministic is preferred**: explanations should be reproducible from persisted/logged inputs.
- **LLM is optional**: a language model may be used to improve readability, but it must not be the sole source of truth.
  - Any LLM-produced prose must be grounded in deterministic factor/evidence fields.
  - The underlying factor attribution and confidence metadata must remain auditable.

## Contents

- `interfaces.py`
  - `DecisionNarrative`
  - `ContributingFactors`
  - `ConfidenceStatement`
  - `DecisionExplainer` (provider protocol)
  - `explain_decision(decision_id)` (contract-only stub)

