# Strategy Attribution & Explainability (vNEXT)

This module defines **schema-first** contracts for explaining *why* a strategy made or lost money over a time window.

## Explainability > optimization

Attribution is an operator/auditor-facing artifact:
- It should **reduce ambiguity** during incidents and post-mortems.
- It should **explain realized outcomes** (fills, slippage, exposure, regime), not justify backtest narratives.
- It should **avoid “optimizer bait”** (do not expose raw knobs that invite overfitting).

If a factor can’t be stated clearly enough to be checked by a human, it doesn’t belong in the snapshot.

## Audit-first mindset

The contracts are strict by default:
- **Forbid extra fields**: untracked data is a risk in audits.
- **Deterministic inputs**: each `AttributionFactor.inputs` should be JSON-serializable and stable.
- **Reproducibility hooks**: `StrategyAttributionSnapshot.audit` should capture dataset versions, query params, and hashes needed to reproduce.

## Primary schemas

- `AttributionFactor`: one human-readable driver of performance (with contribution + evidence).
- `StrategyAttributionSnapshot`: an auditable, point-in-time summary for a `strategy_id` over an `AttributionWindow`.

## Interface boundary

Providers implement:
- `get_attribution(strategy_id, window)` returning a `StrategyAttributionSnapshot`

This keeps the system schema-first: storage/compute can evolve behind the interface while downstream consumers remain stable.

