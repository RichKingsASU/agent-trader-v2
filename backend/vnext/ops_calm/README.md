# Ops Calm Dashboard (Human-Centric)

This module defines **operator-facing calm signals**: a small set of discrete states and actionable hints that help humans quickly understand “are we okay?” without being flooded by noisy telemetry.

## Principles

- **Reduce anxiety**
  - Prefer a single, stable state over dozens of constantly changing numbers.
  - Use *discrete* categories (`GREEN` / `YELLOW` / `RED`) rather than scores that invite over-interpretation.
  - Keep messages short and consistent.

- **Avoid noisy metrics**
  - Do not surface high-frequency counters, per-second gauges, or rapidly oscillating values as primary signals.
  - If metrics exist underneath, translate them into stable **reason codes** and **operator actions**.
  - Low-cardinality fields (e.g. `reason_codes`) are easier to search and safer to aggregate.

## Interface definitions

See `interfaces.py`:

- `CalmState`: discrete operator state (`GREEN`, `YELLOW`, `RED`)
- `SystemHealth`: calm snapshot (headline, reasons, hints)
- `OperatorActionHint`: concrete next steps (optionally with a runbook reference)
- `OpsCalmProvider.get_calm_state()`: the interface for producing a `SystemHealth` snapshot

