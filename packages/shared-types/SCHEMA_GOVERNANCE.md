## Purpose

This package defines **typed, explicit Pub/Sub event schemas** that are shared across AgentTrader services, agents, and infrastructure.

All Pub/Sub messages should conform to the common envelope:

- **eventType**: stable identifier for routing/analytics
- **schemaVersion**: integer version of the schema for that `eventType`
- **producedAt**: ISO-8601 timestamp string when the producer created the event
- **source**: where the event originated (`vm` / `service` / `agent`)
- **payload**: event-specific, typed data

The canonical envelope type is `PubSubEvent` in `src/pubsub.ts`.

## Naming

- **eventType** MUST be **dot-delimited**, lowercase, and stable.
  - Good: `market.bar`, `market.trade`, `mission_control.event`
  - Avoid: `MarketBar`, `marketBar`, `market/bar`
- Names should reflect **domain**, not implementation details.
- Do not encode version in `eventType` (use `schemaVersion`).

## Versioning rules

### What counts as non-breaking (no version bump)

- Adding **optional** fields anywhere in `payload` or `source.meta`
- Adding new event types (new `eventType` strings)
- Expanding permissive unions with additional literal values (e.g. new venues/providers)

### What counts as breaking (requires schemaVersion bump)

- Adding a **required** field to `payload` or envelope
- Removing a field
- Renaming a field
- Changing the meaning/units of a field (e.g. price in dollars → cents)
- Tightening types in a way that rejects previously valid messages

### How to publish a new version safely

- Create a new payload type: `XxxPayloadV2`
- Create a new event schema type: `XxxEventV2` with `schemaVersion: 2`
- Keep the old exported types (`...V1`) indefinitely or until all consumers are migrated
- If you need a union, provide a convenience union type:
  - `type XxxEvent = XxxEventV1 | XxxEventV2`

## Timestamp guidance

- **producedAt**: when the producer created the message (envelope)
- Domain timestamps belong in **payload** (e.g. `tradedAt`, `observedAt`, `startAt/endAt`)
- Use ISO-8601 strings (RFC3339) to keep cross-language compatibility.

## Source guidance

`source` is required and should be populated as:

- **kind**: one of `vm | service | agent`
- **name**: stable logical identifier
  - service: service name (e.g. `execution-engine`)
  - agent: agent name (e.g. `gamma-strategy`)
  - vm: VM/host identifier
- **instanceId**: optional replica/pod/instance identifier
- **meta**: optional debug context (additive-only; do not hard-depend in consumers)

## Payload guidelines

- Prefer stable, explicit names (`instrument`, `price`, `size`) over ambiguous ones.
- Prefer **additive** evolution (new optional fields) over edits to existing fields.
- Use `meta?: Record<string, unknown>` for provider-specific extras when needed.

