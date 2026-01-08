# Contracts unification plan: shared-types ↔ backend messaging envelopes

## Context / problem statement

Today the repo has **multiple “envelope-like” contracts** that overlap but do not fully agree:

- **Python (agent-to-agent / Pub/Sub publisher)**: `backend/messaging/envelope.py::EventEnvelope` emits a **snake_case**, **unversioned** JSON object with:
  - `event_type`, `agent_name`, `git_sha`, `ts`, `trace_id`, `payload`
- **TypeScript (explicit Pub/Sub envelope)**: `packages/shared-types/src/pubsub.ts::PubSubEvent` defines a **camelCase**, **versioned** envelope with:
  - `eventType`, `schemaVersion`, `producedAt`, `source`, `payload`
- **TypeScript (Python-compatible envelope)**: `packages/shared-types/src/envelope.ts::EventEnvelope` intentionally matches the Python snake_case envelope.

This creates **contract drift risk**:

- Producers/consumers disagree on casing, field names, and whether versioning exists.
- Consumers fall back to best-effort heuristics (e.g., `event_type` vs `eventType`), which hides incompatibilities until runtime.
- The repo cannot reliably generate or validate a single JSON Schema for “the envelope”, because there isn’t one.

## Goal

Eliminate drift by establishing **one canonical EventEnvelope** (wire contract) with a clear **versioning strategy**, plus:

- **JSON Schema** generation/distribution for the envelope and event payloads
- A **lightweight consumer-side runtime validator** that **rejects unknown `schemaVersion` / `eventType`**

Constraints for this deliverable:

- **No code changes** in this PR (plan + docs only).

---

## Proposed canonical contract: `EventEnvelope` (wire format)

### Decision: canonicalize on the `PubSubEvent` shape (camelCase)

Rationale:

- `packages/shared-types` already has governance and naming rules centered around `eventType` + `schemaVersion`.
- The requested runtime guard explicitly mentions `schemaVersion` / `eventType`.
- CamelCase aligns with common JSON conventions for cross-language services and public-facing contracts.

The existing snake_case Python envelope becomes a **legacy compatibility shape**, accepted during migration via explicit alias normalization (see “Migration strategy”).

### Canonical `EventEnvelope` fields (v1)

This is the **single** contract to put inside Pub/Sub `message.data` (UTF-8 JSON):

- **`eventType`**: `string` (required)
  - Stable, lowercase, dot-delimited (e.g. `market.bar.1m`, `ops.system_event`, `trade.signal`)
- **`schemaVersion`**: `integer` (required)
  - Version of the schema for this `eventType` (see versioning rules below)
- **`eventId`**: `string` (required)
  - Globally unique identifier (UUID recommended); MAY reuse Pub/Sub `messageId` when present
- **`producedAt`**: `string` (required)
  - RFC3339/ISO-8601 timestamp (UTC recommended)
- **`source`**: `object` (required)
  - `kind`: `"vm" | "service" | "agent"` (required)
  - `name`: `string` (required; stable logical identity)
  - `instanceId`: `string` (optional; pod/revision/replica identifier)
  - `meta`: `object` (optional; debug-only, additive-only)
- **`traceId`**: `string` (optional but strongly recommended)
  - Correlation id for tracing/log stitching across flows
- **`payload`**: `object` (required)
  - Event-specific schema; MUST be a JSON object (not array/scalar) for cross-language stability

### Legacy aliases to accept (during migration)

Consumers SHOULD normalize legacy keys into the canonical fields above, before validation/routing:

- `event_type` / `type` → `eventType`
- `schema_version` → `schemaVersion`
- `ts` → `producedAt`
- `trace_id` → `traceId`
- `agent_name` → `source.name` (with `source.kind="agent"` default)
- `git_sha` → `source.meta.gitSha`

Important: aliases are **parsing-time affordances**, not part of the long-term contract. The long-term goal is for all producers to emit canonical fields only.

---

## Versioning strategy

### What `schemaVersion` means

`schemaVersion` is the **version of the event schema** for a specific `eventType`, including:

- the envelope invariants that the system relies on (`eventType`, `schemaVersion`, `producedAt`, `source`, `payload`, etc.)
- the **payload schema** for that event type/version

### Rules

- **Non-breaking (no bump)**:
  - Add optional fields anywhere in `payload`
  - Add optional fields in `source.meta`
  - Add new event types (new `eventType` values)
- **Breaking (bump `schemaVersion`)**:
  - Add a required field to `payload`
  - Remove/rename a field
  - Change type/meaning/units in a way that would reject previously valid messages
  - Tighten constraints (e.g. make a field non-nullable, restrict enum values)

### Compatibility window

For each `eventType`, producers/consumers should support:

- **Current version** and **at least one prior version** during a migration window
- Explicit deprecation policy (recommended):
  - “Support N-1 for 30 days” (or similar), documented per eventType

### Registry of supported schemas (source of truth)

To prevent “unknown schemaVersion” from silently flowing through the system, maintain a **registry** mapping:

- `eventType` → supported `schemaVersion[]` → schema file reference (JSON Schema)

This registry is what the consumer validator uses to **reject unknown combinations**.

---

## JSON Schema strategy (envelope + payloads)

### Recommended: schema-first (JSON Schema is canonical)

Single source of truth:

- A JSON Schema file per `(eventType, schemaVersion)` and one for the base envelope.

Generated artifacts:

- **TypeScript types** in `packages/shared-types` generated from JSON Schema (ensures TS cannot drift).
- **Python models** in backend generated from the same JSON Schema (ensures Python cannot drift).

Suggested tooling (examples; pick one consistent stack):

- **TS generation**: `json-schema-to-typescript`
- **Python generation**: `datamodel-code-generator` (Pydantic models) or a small TypedDict layer

### Alternative: TS-first (generate JSON Schema from TypeScript)

If the team prefers `packages/shared-types` to remain the authoring surface:

- Define concrete, non-generic `EventEnvelopeV1` + per-event payload types in TS
- Generate JSON Schemas at build time using `ts-json-schema-generator`
- Treat the generated schema outputs as published artifacts and validate Python against them

Tradeoff: TS-first is convenient for TS authors, but **cross-language correctness** depends on schema generation fidelity and avoiding TS-only features that don’t map cleanly to JSON Schema.

### Publishing/distribution

Regardless of authoring approach, consumers need schemas at runtime/CI. Recommended:

- Store generated/authoritative schemas inside `packages/shared-types` as build artifacts (e.g. `packages/shared-types/schemas/**`)
- Publish them with the package so any service can depend on a specific version of the schemas

---

## Consumer-side runtime validator (lightweight guardrail)

### Objective

At the **ingress edge** (e.g., Pub/Sub push handler, stream bridge, message router), reject messages that are:

- syntactically not JSON objects
- missing canonical envelope keys after alias normalization
- **unknown `eventType`**
- **unknown `schemaVersion` for a known `eventType`**

This is intentionally “lightweight”: it prevents silent drift and undefined routing behavior.

### Recommended validation flow

1. **Decode** bytes → JSON object
2. **Normalize** legacy aliases into canonical keys (temporary)
3. **Extract** `eventType` + `schemaVersion`
4. **Lookup** `(eventType, schemaVersion)` in the schema registry:
   - If not found: **reject** (NACK / DLQ / 2xx-ack-with-store-only depending on service semantics)
5. (Optional but recommended) Validate the full message against the referenced JSON Schema:
   - If invalid: **reject** with reason “schema_validation_failed”

### Rejection behavior (operationally safe)

To avoid infinite redelivery loops while still surfacing issues:

- **Primary consumers (business logic)**: reject in a way that routes to DLQ (or NACK with retries capped)
- **Visibility-only ingestors**: can ACK but record as “invalid/unknown” with metrics and sampled payload capture

Emit metrics/logs on every rejection with:

- `eventType`, `schemaVersion`, `producer` (if available from `source.name`), and `reason`

---

## Migration strategy (no-breaking, staged)

### Phase 0: contract declaration + registry

- Publish the canonical `EventEnvelope` contract (this doc)
- Define the schema registry structure and ownership (who approves new eventTypes/versions)

### Phase 1: schema authoring + generation pipeline

- Implement JSON Schema generation (schema-first or TS-first)
- Ensure schemas are published with `packages/shared-types`
- Add CI checks:
  - schema files are valid JSON Schema (draft pinned)
  - registry references are consistent

### Phase 2: consumer guardrail

- Add the lightweight validator at ingress points
- Start by “warn-only” mode (metrics/logs) then tighten to “reject unknown”

### Phase 3: producer convergence

- Update Python publishers to emit canonical `EventEnvelope` fields (camelCase) and include `schemaVersion`
- Update any payload-only publishers (e.g., system events) to wrap with the canonical envelope

### Phase 4: remove legacy affordances

- Stop emitting legacy snake_case fields
- Remove alias normalization code and legacy schemas after deprecation window

---

## Success criteria

- **Single canonical envelope** referenced by both TS and Python (no parallel “envelope” definitions)
- Schemas are **published** and **consumed** from one place (no copy/paste drift)
- Consumers **reject unknown `(eventType, schemaVersion)`** with clear observability
- Adding/changing event contracts requires explicit versioning and passes CI contract checks

---

## Assumptions / notes

- Pub/Sub push “delivery wrapper” is out of scope; this plan governs only `message.data` (application envelope).
- Existing snake_case producers/consumers remain supported during migration via alias normalization, but the end state is canonical camelCase only.

