# Event Contract v1 — Canonical `EventEnvelope`

## Status

- **Status**: Proposed (design-only; no code changes in this document)
- **Scope**: Canonical event envelope for agent-to-agent messaging and Pub/Sub transport
- **Audience**: Producers/consumers in Python (`backend/*`) and TypeScript (`packages/shared-types/*`)

## Goals & constraints

- **Single canonical schema** for all cross-service events.
- **Backward compatible where possible** with existing envelopes and ingestion behavior.
- **Explicit `schemaVersion` field** at the envelope level.
- **Generic payload**: event-specific content lives under `payload` and may vary by `event_type`.
- **Stable metadata** for traceability, audit, and operational debugging.
- **Additive evolution**: adding optional fields is non-breaking; breaking changes require bumping `schemaVersion`.

## Repository reality (what exists today)

There are currently multiple “envelope-like” shapes:

- **Python**: `backend/messaging/envelope.py` defines an unversioned, snake_case JSON envelope with required fields:
  - `event_type`, `agent_name`, `git_sha`, `ts`, `payload`, `trace_id`
- **TypeScript (snake_case)**: `packages/shared-types/src/envelope.ts` defines `EventEnvelope<TPayload>` matching Python **1:1** at JSON level, also unversioned.
- **TypeScript (camelCase, versioned)**: `packages/shared-types/src/pubsub.ts` defines `PubSubEvent<eventType, schemaVersion, payload>` with:
  - `eventType`, `schemaVersion`, `producedAt`, `source`, `payload`
- **Mission Control (camelCase, versioned record shape)**: `packages/shared-types/src/mission-control.ts` defines an `EventEnvelopeV1` used for Mission Control API records (not the same as Python envelope).

This document proposes a **single canonical wire contract** that:

- preserves existing snake_case fields as canonical (to avoid breaking current Python tooling), and
- introduces the missing **`schemaVersion`** (and compatible aliases) so TS `PubSubEvent` and future producers can converge.

## Canonical EventEnvelope v1 (wire format)

### Canonical field names (MUST emit)

All producers **MUST** emit the following fields:

- **`schemaVersion`**: integer (for this document: `1`)
  - Increment only on backward-incompatible changes to required fields or semantics.
- **`event_type`**: string
  - Stable event identifier. Recommended: lowercase, dot-delimited namespace (e.g. `market.tick`), but this contract supports existing underscore styles (e.g. `system_event`).
- **`ts`**: string (RFC3339/ISO-8601 timestamp; UTC recommended)
  - Producer timestamp for when the event was created (equivalent to “produced at”).
- **`agent_name`**: string
  - Logical producer identity (service/agent name). Must be stable across restarts.
- **`git_sha`**: string
  - Producer build/source version identifier (commit SHA or `unknown`).
- **`trace_id`**: string
  - Correlation identifier for log stitching and distributed tracing.
- **`payload`**: object (JSON map)
  - Event-specific content. Must be JSON-serializable. **Must be an object** (not array/scalar) for cross-language compatibility.

### Optional fields (MAY emit)

Optional fields are additive and must not be required by consumers.

- **`event_id`**: string
  - Globally unique id for the event (UUID recommended). Useful for idempotency across transports.
  - Note: current Pub/Sub ingestion may dedupe on Pub/Sub `messageId`; `event_id` is for end-to-end semantics.
- **`source`**: object
  - Structured producer origin metadata (aligned with TS `PubSubSource`).
  - Recommended shape:
    - `kind`: `"vm" | "service" | "agent"`
    - `name`: string (stable)
    - `instanceId`: string (optional, per replica)
    - `meta`: object (optional, debug-only)
- **`replay`**: object
  - Optional replay/backfill context (e.g., `is_replay`, `replay_id`, `original_ts`). Consumers must not rely on it.
- **`meta`**: object
  - Freeform envelope-level metadata. Treat as debug context; do not make it required.

### Backward-compatibility aliases (MUST accept)

Consumers **MUST** accept these legacy aliases when parsing incoming events (best-effort), and normalize to the canonical names above internally:

- `eventType` → `event_type`
- `producedAt` → `ts`
- `agentName` → `agent_name`
- `gitSha` / `sha` → `git_sha`
- `traceId` / `correlation_id` → `trace_id` (if both exist, prefer `trace_id`)
- `schema_version` → `schemaVersion`

Notes:

- Producers should **not** emit both canonical and alias fields long-term. During migration, emitting both is permitted, but canonical fields win on conflict.
- Existing extractors in the repo already tolerate `event_type` / `eventType` / `type` in some places; this contract formalizes that tolerance at the envelope boundary.

## Semantics & invariants

### Event identity

- **`event_type`** identifies the schema/meaning of `payload`.
- **`schemaVersion`** identifies the envelope contract version (this document is v1).
  - Payload versioning is handled by the combination of `event_type` and the payload schema referenced by that type. If a payload requires breaking changes, either:
    - publish a new `event_type` (preferred, e.g. `market.tick.v2`), or
    - introduce an event-type-specific payload versioning strategy inside `payload` (less preferred).

### Time

- `ts` is the producer-created timestamp (RFC3339/ISO-8601). Example: `2026-01-08T12:34:56.789Z`.
- If the payload contains domain timestamps (e.g. `observedAt`, `tradedAt`), those represent *market observation time* and may differ from `ts`.

### Tracing and correlation

- `trace_id` is required and must remain stable across related events in a flow (e.g. signal → order → fill).
- If a system already has `correlation_id` or HTTP `request_id`, it may be included inside `payload` (as in `SystemEventPayload`), but `trace_id` remains the envelope-level key.

### Payload constraints

- `payload` must be a JSON object.
- Consumers must ignore unknown fields within `payload` unless they are explicitly required by the payload schema for that `event_type`.

## Evolution rules

- **Non-breaking (allowed in v1)**:
  - Add optional fields to the envelope.
  - Add optional fields to a payload.
  - Add new `event_type` values.
- **Breaking (requires `schemaVersion` bump or new `event_type`)**:
  - Remove/rename required envelope fields.
  - Change meaning/units of any field.
  - Add new required fields to envelope or payload.

## JSON Schema (informative)

This is a **permissive** schema intended for documentation and validation of the envelope surface area. It does not validate payload contents beyond being an object.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "EventEnvelopeV1",
  "type": "object",
  "required": [
    "schemaVersion",
    "event_type",
    "ts",
    "agent_name",
    "git_sha",
    "trace_id",
    "payload"
  ],
  "properties": {
    "schemaVersion": { "type": "integer", "const": 1 },
    "event_type": { "type": "string", "minLength": 1 },
    "ts": { "type": "string", "minLength": 1 },
    "agent_name": { "type": "string", "minLength": 1 },
    "git_sha": { "type": "string", "minLength": 1 },
    "trace_id": { "type": "string", "minLength": 1 },
    "payload": { "type": "object" },

    "event_id": { "type": "string" },
    "source": {
      "type": "object",
      "properties": {
        "kind": { "type": "string", "enum": ["vm", "service", "agent"] },
        "name": { "type": "string" },
        "instanceId": { "type": "string" },
        "meta": { "type": "object" }
      },
      "required": ["kind", "name"],
      "additionalProperties": true
    },
    "meta": { "type": "object" },

    "eventType": { "type": "string" },
    "producedAt": { "type": "string" },
    "agentName": { "type": "string" },
    "gitSha": { "type": "string" },
    "traceId": { "type": "string" },
    "schema_version": { "type": "integer" }
  },
  "additionalProperties": true
}
```

## Canonical examples

### Example: `system_event`

```json
{
  "schemaVersion": 1,
  "event_type": "system_event",
  "ts": "2026-01-08T13:45:12.123Z",
  "agent_name": "strategy-engine",
  "git_sha": "9f3c2e1",
  "trace_id": "7d2b2b3b3f4c4c4e9b7c8f6a1a2b3c4d",
  "payload": {
    "timestamp": "2026-01-08T13:45:12.123Z",
    "severity": "INFO",
    "service": "strategy-engine",
    "env": "prod",
    "version": "1.2.3",
    "sha": "9f3c2e1",
    "git_sha": "9f3c2e1",
    "image_tag": "strategy-engine:1.2.3",
    "agent_mode": "live",
    "request_id": "req_01HZXV6N2C9YJ4K8W0Q1T2R3S4",
    "correlation_id": "7d2b2b3b3f4c4c4e9b7c8f6a1a2b3c4d",
    "event_type": "intent.start",
    "event": "intent.start",
    "message": "Intent evaluation started"
  }
}
```

### Example: `market_tick`

```json
{
  "schemaVersion": 1,
  "event_type": "market_tick",
  "ts": "2026-01-08T13:45:12.500Z",
  "agent_name": "market-ingest",
  "git_sha": "9f3c2e1",
  "trace_id": "c1a0f0c0d0e0f0001111222233334444",
  "payload": {
    "instrument": { "symbol": "AAPL", "assetClass": "equity" },
    "observedAt": "2026-01-08T13:45:12.490Z",
    "bid": 192.31,
    "bidSize": 200,
    "ask": 192.33,
    "askSize": 100,
    "last": 192.32,
    "lastSize": 50,
    "provider": "alpaca",
    "venue": "NASDAQ",
    "meta": {
      "feed": "sip",
      "sequence": 123456789
    }
  }
}
```

### Example: `trade_signal`

```json
{
  "schemaVersion": 1,
  "event_type": "trade_signal",
  "ts": "2026-01-08T13:45:13.000Z",
  "agent_name": "whale-strategy",
  "git_sha": "9f3c2e1",
  "trace_id": "c1a0f0c0d0e0f0001111222233334444",
  "payload": {
    "action": "buy",
    "symbol": "AAPL",
    "notional_usd": 25000,
    "reason": "Momentum + flow confirmation",
    "raw_model_output": {
      "score": 0.83,
      "threshold": 0.70,
      "features": { "flow_z": 2.1, "trend": 1.4 }
    }
  }
}
```

## Alignment map (recommended normalization)

When ingesting events from mixed producers, normalize to the canonical v1 keys:

- `event_type`: choose first present from [`event_type`, `eventType`, `type`]
- `ts`: choose first present from [`ts`, `producedAt`, `timestamp`]
- `agent_name`: choose first present from [`agent_name`, `agentName`, `agent`]
- `git_sha`: choose first present from [`git_sha`, `gitSha`, `sha`]
- `trace_id`: choose first present from [`trace_id`, `traceId`, `correlation_id`]
- `schemaVersion`: choose first present from [`schemaVersion`, `schema_version`], defaulting only in controlled migration layers (do not silently default at the edge long-term)

