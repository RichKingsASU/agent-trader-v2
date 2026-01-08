## Canonical Pub/Sub Contracts (Contract Unification Gate)

This folder is the **single source of truth** for Pub/Sub message schemas for the topics:

- `system-events`
- `market-ticks`
- `market-bars-1m`
- `trade-signals`

Schemas live in `contracts/schemas/` and **MUST** be enforced:

- **at runtime** in both publisher and consumer (invalid events are not processed; they are recorded for ops and ACK’d)
- **in CI** via contract tests (schema drift breaks CI)

### Canonical wire format

For these topics, the canonical wire payload (Pub/Sub `message.data`) is:

- **`EventEnvelopeV1`** (snake_case) with required `schemaVersion: 1`
- topic-specific `payload` constraints per schema file

### Breaking vs non-breaking change rules

- **Non-breaking (no `schemaVersion` bump)**:
  - Add a new **optional** field.
  - Widen an enum (add new allowed value) when consumers treat unknown values safely.
  - Add new topic schemas / new event types.

- **Breaking (requires `schemaVersion` bump + parallel support window)**:
  - Add a new **required** field.
  - Remove or rename any field.
  - Change meaning/units (e.g., dollars → cents).
  - Tighten validation such that previously-valid messages become invalid.

### How to change a contract

1. Update the topic schema in `contracts/schemas/<topic>.v<schemaVersion>.schema.json`
2. Update/add fixtures in `contracts/fixtures/<topic>/`
3. Ensure runtime validation continues to pass for existing producers/consumers

CI will fail if:

- schemas are invalid JSON Schema
- any fixture does not validate against its referenced schema
- required schema/fixture coverage is missing

