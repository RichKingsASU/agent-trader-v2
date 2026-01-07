# vNEXT Explainability (Schema Only)

This package defines the **narrative schema** used to explain decisions in vNEXT.

## Governance

- **Explainability is mandatory for promotion**: a decision/output is not eligible for promotion unless it includes a complete `DecisionNarrative`.
- **LLM is optional; deterministic is preferred**: narratives should be generated deterministically whenever possible (rule-based, trace-based, template-based). LLMs may be used only as an *augmentation layer* and must not be required for core correctness.

## What this package contains

- `DecisionNarrative`: the canonical explanation record for a single decision.
- `ContributingFactors`: a structured list of drivers (and explicit exclusions).
- `ConfidenceStatement`: bounded confidence with rationale and limitations.
- `DecisionExplainer`: interface exposing `explain_decision(decision_id) -> DecisionNarrative`.

## What this package intentionally does *not* contain

- No I/O, storage clients, network calls, broker/execution coupling, or runtime dependencies on LLM services.
- No implementation of `DecisionExplainer` (schema only).

