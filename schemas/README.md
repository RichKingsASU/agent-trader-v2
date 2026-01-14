## JSON Schemas (governed contracts)

This directory contains **versioned JSON Schemas** derived from the TypeScript event payload types in `packages/shared-types/src`.

### What’s here

- **`schemas/v1/system_event.json`**: schema for `SystemEventPayload` (payload-only).
- **`schemas/v1/market_tick.json`**: schema for `MarketTickPayloadV1` (payload-only; carried as `payload` inside the Pub/Sub envelope type).
- **`schemas/v1/trade_signal.json`**: schema for `TradeSignalPayload` (payload-only).

Each schema includes:

- **`$schema`**: JSON Schema draft (2020-12).
- **`$id`**: a stable identifier (URN) suitable for downstream registries and `$ref` resolution.
- **`x-schemaVersion`**: a simple integer to mirror versioning intent; the authoritative version is also encoded by the path (`schemas/v1/...`).
- **`required`**: derived from non-optional fields in the TS payload types.

### How these will be used later (not wired yet)

- **Producer-side validation (optional)**: publishers can validate outgoing payloads against the matching schema version before publishing.
- **Consumer-side validation (recommended at boundaries)**: consumers validate incoming messages at the transport boundary (e.g. Pub/Sub handler, HTTP ingress) and reject/quarantine invalid payloads.
- **Contract testing**: CI can later assert that:
  - payload examples / fixtures validate against these schemas
  - breaking changes are only introduced by publishing a new schema version (e.g. `schemas/v2/...`)
- **Schema registry**: the `$id` values are designed to be compatible with registering schemas in a registry/catalog (internal or third-party) and referencing them from documentation or event metadata.

### Versioning rules (practical)

- **Additive changes** (safe):
  - add optional fields
  - widen string “code” sets (providers/venues/etc.)
- **Breaking changes** (require new version directory and `$id`):
  - add a required field
  - rename/remove fields
  - change semantics/units of existing fields

### Notes

- These schemas are **payload-only** by design. Transport envelopes (e.g. Pub/Sub envelope types) can have their own separate schemas later if needed.
- No runtime code or CI integration is modified as part of introducing these files.

