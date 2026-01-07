# Operator annotations & overrides (vNEXT)

This folder provides **non-invasive scaffolding** for storing and retrieving operator-authored notes and overrides.

## Semantics

- **Advisory by default**: overrides are informational unless a consuming component **explicitly enforces** them.
  - `OperatorNote.enforced=False` is the safe default.
  - Even when `enforced=True`, enforcement behavior is owned by the consumer policy (outside this package).
- **Auditable**: all overrides/annotations are intended to be recorded as immutable facts:
  - who (`created_by`)
  - when (`created_at_utc`)
  - why (`reason`, `reason_detail`, `message`)
  - what scope (`scope`, plus `strategy_name` / `symbol`)
  - optional expiration (`expires_at_utc`)

## Interface

Consumers can depend on the boundary protocol:

- `OperatorOverridesProvider.get_active_overrides()`

Implementations (Firestore, file, etc.) should live outside vNEXT compute logic and simply return active `OperatorNote` records.

