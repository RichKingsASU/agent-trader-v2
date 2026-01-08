# Contract Lockdown — EventEnvelope v1 (Python ⇄ TypeScript)

Goal: stop schema drift by defining **one canonical wire envelope**, keeping backward compatibility via **aliases**, and enforcing **`schemaVersion`** at publish + consume boundaries.

## 1) What’s drifting today (mismatches)

### Envelope shapes in this repo

- **Python envelope (legacy, snake_case, previously unversioned)**: `backend/messaging/envelope.py::EventEnvelope`
  - Fields: `event_type`, `agent_name`, `git_sha`, `ts`, `trace_id`, `payload`
  - Problem: **no `schemaVersion`** → consumers can’t reliably validate/route versions.

- **TypeScript envelope (legacy, snake_case, previously unversioned)**: `packages/shared-types/src/envelope.ts::EventEnvelope`
  - Matches Python legacy envelope **1:1** at JSON level.
  - Problem: also **no `schemaVersion`**.

- **TypeScript Pub/Sub envelope (versioned, camelCase)**: `packages/shared-types/src/pubsub.ts::PubSubEvent`
  - Fields: `eventType`, `schemaVersion`, `producedAt`, `source`, `payload`
  - Problem: different naming + different field set than the Python envelope.

### Naming differences observed / required aliases

| Concept | Canonical v1 key | Legacy / alias keys seen in repo |
|---|---|---|
| Envelope version | `schemaVersion` | `schema_version` (legacy), absent (legacy v0) |
| Event type | `event_type` | `eventType`, `type` |
| Producer identity | `agent_name` | `agentName` |
| Code version | `git_sha` | `gitSha`, `sha` |
| Produced timestamp | `ts` | `producedAt` |
| Trace/correlation | `trace_id` | `traceId` |

### Producer/consumer boundary mismatch (wire vs payload-only)

Some consumers (notably the Cloud Run Pub/Sub push materializer) historically treated `message.data` as **payload-only**. Meanwhile, Python publishers send an **envelope object** with nested `payload`.

v1 formalizes the envelope boundary and requires consumers to:
- accept **payload-only** as legacy input, and
- if an envelope is detected, **validate `schemaVersion` and unwrap** to the inner payload.

## 2) Canonical EventEnvelope v1 (wire format)

### Contract

This is the **single canonical** JSON shape for Pub/Sub `message.data`:

```json
{
  "schemaVersion": 1,
  "event_type": "market.bars.1m",
  "agent_name": "vm-bars-ingest",
  "git_sha": "abc123",
  "ts": "2026-01-08T12:34:56.789+00:00",
  "trace_id": "d34db33f...",
  "payload": { "any": "json object" }
}
```

### Rules

- **`schemaVersion` is REQUIRED** and must be an integer.
- **Backward compatible**:
  - Adding *optional* fields is always OK.
  - Existing keys are **never renamed**; if a new name is introduced, the old name remains accepted as an alias.
- **No renames without aliases**:
  - Consumers must accept the alias keys listed in the table above.
  - Producers should emit **only the canonical keys**.
- **Unknown fields**:
  - Consumers must ignore unknown top-level envelope fields.
  - Consumers must ignore unknown payload fields unless the payload schema for that `event_type` says otherwise.

## 3) Canonical types

### Python (dataclass)

Implemented in `backend/messaging/envelope.py` as `EventEnvelope` (now v1):
- Emits `schemaVersion` in `to_dict()` / `to_json()`
- Accepts aliases on `from_dict()` / `from_bytes()`

### TypeScript (interface)

Implemented in `packages/shared-types/src/envelope.ts`:
- `EventEnvelope` (legacy, schema-less)
- `EventEnvelopeV1` (canonical, `schemaVersion: 1`)
- `isEventEnvelopeV1()` runtime guard

## 4) Enforcement (publish + consume)

### Publish-time enforcement

Publishers must:
- set `schemaVersion: 1` in the JSON envelope
- duplicate it into Pub/Sub attributes as `schemaVersion="1"` (string)

Enforced in:
- `backend/messaging/publisher.py` (rejects unsupported `schemaVersion`)

### Consume-time enforcement

Consumers must:
- if an envelope is present: **require** `schemaVersion` and reject unsupported versions
- optionally allow legacy schema-less envelopes only via an explicit migration toggle

Enforced in:
- `backend/messaging/envelope.py` (`from_dict` requires `schemaVersion` unless `ALLOW_LEGACY_SCHEMALESS_ENVELOPE` is enabled)
- `backend/messaging/subscriber.py` (rejects unsupported `schemaVersion`)
- `cloudrun_consumer/main.py` (unwraps EventEnvelope v1 and rejects missing/invalid/unsupported `schemaVersion`)

## 5) Migration knobs (explicit, temporary)

To keep legacy flows alive during rollout:

- **`ALLOW_LEGACY_SCHEMALESS_ENVELOPE=1`** (Python): allows parsing envelopes without `schemaVersion` as `schemaVersion=0`.
  - Default: **off** (strict).
  - Intended use: short migration window only.

