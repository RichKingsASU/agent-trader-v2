# Market Regime (vNEXT) — Schema Only

This module defines **advisory** market regime primitives used to *annotate* market context.

## Key principles

- **Regimes are advisory**: a regime is a label that can help interpret signals, not a directive.
- **Strategies may down-weight signals**: strategies can reduce position sizing *recommendations*,
  widen filters, or require higher confidence when the regime is unfavorable.
- **No execution logic allowed**: this package must not contain broker calls, order placement,
  routing, portfolio mutation, or any side-effectful trading actions.

## What belongs here

- Enum + dataclass schema definitions (e.g., `MarketRegime`, `RegimeSnapshot`)
- Thin interface stubs (e.g., `get_current_regime(...)`) that are implemented elsewhere

## What does **not** belong here

- Strategy logic (entries/exits), risk overrides, or “force trade/close” behavior
- Network I/O, Firestore reads/writes, broker SDK usage, or scheduling

