# Contract alignment plan (Pub/Sub payloads)

## Scope (this doc)

Map and reconcile:

- **cloudrun_ingestor published payloads** (what producers put into Pub/Sub `message.data` + attributes)
- **cloudrun_consumer expected payloads** (what the Cloud Run Pub/Sub push handler decodes and routes on)
- **`packages/shared-types` definitions** (TypeScript “source of truth” types for payload/envelope)

Deliverables:

- Identify **mismatches**
- Propose a **temporary compatibility shim** strategy (**no runtime changes in this PR**)
- Define **canonical v1 envelope fields**

Non-goals:

- No code/runtime changes, no topic/subscription mutations, no deployments.

---

## What exists today

### Pub/Sub push wrapper (transport)

Both `cloudrun_consumer` and `backend/ingestion/pubsub_event_store.py` implement the standard Pub/Sub push wrapper:

- `body.message.data`: base64-encoded bytes (here: UTF-8 JSON)
- `body.message.messageId`: Pub/Sub message id
- `body.message.publishTime`: Pub/Sub publish timestamp
- `body.message.attributes`: string map
- `body.subscription`: subscription name

This wrapper is **not the application envelope**; it is the delivery envelope.

---

## Producers (“cloudrun_ingestor”) — what is published

There are two distinct producer patterns in-repo that lead to Pub/Sub deliveries into consumers:

### A) Python `EventEnvelope` (snake_case) published in `message.data`

Producer implementation:

- `backend/messaging/publisher.py` publishes bytes from `backend/messaging/envelope.py::EventEnvelope.to_bytes()`
- It also duplicates key fields as Pub/Sub attributes:
  - `event_type`, `agent_name`, `trace_id`, `git_sha`, `ts`

JSON shape (data payload):

- `event_type: string`
- `agent_name: string`
- `git_sha: string`
- `ts: string` (ISO-8601)
- `trace_id: string`
- `payload: object` (event-specific)

Example payload contract in shared types:

- Market bars:
  - TS payload: `packages/shared-types/src/market-bars.ts::MarketBar1mPayload`
  - TS envelope adapter: `packages/shared-types/src/market-bars.envelope.ts::MarketBar1mEvent`
  - Python publisher in synthetic mode: `backend/streams/alpaca_bars_ingest.py` publishes `event_type="market.bars.1m"` and payload shaped like `MarketBar1mPayload`

### B) Ops/system “structured log record” published in `message.data` (payload-only)

The “system event” shape is defined by the structured logger:

- Producer shape reference: `backend/observability/ops_json_logger.py`
- TS payload type: `packages/shared-types/src/system-event.ts::SystemEventPayload`

JSON shape (data payload) includes at minimum:

- `timestamp: string`
- `severity: string`
- `service: string`
- `env: string`
- `version: string`
- `sha: string`
- `git_sha: string` (back-compat alias)
- `event_type: string` (and `event` alias)
- plus additional freeform fields

Important: this is **payload-only** (not wrapped in `EventEnvelope`).

---

## Consumers (“cloudrun_consumer”) — what is expected

### Cloud Run Pub/Sub → Firestore materializer (Phase 1)

Consumer implementation:

- HTTP handler: `cloudrun_consumer/main.py`
- Router: `cloudrun_consumer/schema_router.py`
- Handler: `cloudrun_consumer/handlers/system_events.py`

What it does:

1. Decodes `message.data` as UTF-8 JSON and requires it to be a JSON object.
2. Routes based on payload shape:
   - payload is considered a “system event” if it has:
     - `service` (non-empty string) and
     - `timestamp` (present; any parseable-ish value is handled later)
3. Materializes to Firestore `ops_services/{serviceId}` with dedupe + stale protection.

Fields it actually consumes from the payload (system events):

- **Required**
  - `service` (used as `serviceId`)
- **Used for ordering / recency**
  - `timestamp` (preferred)
  - optional `producedAt`, optional `publishedAt` (validated if present)
  - otherwise falls back to Pub/Sub `publishTime`
- **Used for status**
  - `severity` → `healthy/degraded/down/unknown`
- **Used for version**
  - first non-empty of: `version`, `sha`, `git_sha`
- **Used for region**
  - `region` (optional) else `DEFAULT_REGION`

Notably, this consumer **does not parse** `EventEnvelope` and does not use Pub/Sub attributes for routing.

---

## `packages/shared-types` — what is defined

The shared types currently define *multiple* envelope styles:

### 1) `EventEnvelope` (snake_case) — matches Python 1:1

- `packages/shared-types/src/envelope.ts::EventEnvelope`
- Comment explicitly states it matches `backend/messaging/envelope.py` 1:1 at JSON level.

### 2) `PubSubEvent` (camelCase) — newer “explicit Pub/Sub event schema” envelope

- `packages/shared-types/src/pubsub.ts::PubSubEvent`
- Fields: `eventType`, `schemaVersion`, `producedAt`, `source`, `payload`

### 3) Mission Control event envelope (camelCase, different shape)

- `packages/shared-types/src/mission-control.ts::EventEnvelopeV1` (`schemaVersion`, `eventId`, `producedAt`)
- and then Mission Control Pub/Sub events are typed as `PubSubEvent<...>`

### 4) System event payload

- `packages/shared-types/src/system-event.ts::SystemEventPayload`
- Comment: “Payload-only: wrap with `EventEnvelope<T>` at the transport boundary.”

This creates an ambiguity: **which envelope is canonical for Pub/Sub** right now?

---

## Mismatch matrix (high-signal)

### M1 — Consumer expects payload-only, but producers may publish `EventEnvelope`

- **Producer A** publishes `EventEnvelope` in `message.data`.
- **cloudrun_consumer** routes only on `{service, timestamp}` in the **top-level decoded JSON**.
- Result: an `EventEnvelope` will not route (top-level has `agent_name`, `ts`, etc., not `service`/`timestamp`), unless a producer mistakenly flattens payload into the top-level.

### M2 — `SystemEventPayload` is defined as payload-only but “transport boundary” is inconsistent

- `packages/shared-types` says system events should be payload-only and wrapped at transport boundary.
- `cloudrun_consumer` expects payload-only and does **not** unwrap.
- If a future producer wraps system events in `EventEnvelope`, the current consumer will break routing.

### M3 — Two competing “Pub/Sub envelope” types exist (`EventEnvelope` vs `PubSubEvent`)

- Python uses snake_case `EventEnvelope`.
- TS also defines `PubSubEvent` with camelCase `eventType/schemaVersion/producedAt/source`.
- There is no documented mapping between them, and no single canonical “v1 Pub/Sub envelope” that all producers/consumers agree on.

### M4 — Field naming/versioning is split across snake_case and camelCase

- Pub/Sub attributes and Python envelope: `event_type`, `agent_name`, `git_sha`, `trace_id`, `ts`
- Newer TS Pub/Sub envelope: `eventType`, `schemaVersion`, `producedAt`, `source`
- Consumer expects: `timestamp`, `service`, `severity`, plus optional `producedAt/publishedAt`

### M5 — Topic/source identity is inferred, not carried

- Pub/Sub push payload does not include topic name.
- `cloudrun_consumer` sets `source.topic` from `SYSTEM_EVENTS_TOPIC` env var (configuration, not message truth).
- Producers embedding topic/source in the message would be more canonical, but today it’s not standardized.

---

## Temporary compatibility shim strategy (no producer/consumer changes required now)

Goal: allow producers and consumers to evolve independently while converging on a single canonical envelope.

### Strategy: “contract adapter” republisher (recommended)

Add a dedicated, small service (or function) that:

- Subscribes to **legacy topics** (existing producers)
- Accepts **multiple input shapes**:
  - Shape A: Python `EventEnvelope` (snake_case)
  - Shape B: system/ops log record (`SystemEventPayload`, payload-only)
- Normalizes into **Canonical Pub/Sub Envelope v1** (defined below)
- Republishes to **new v1 topics** (e.g. `system.events.v1`, `market-bars-1m.v1`, etc.)
- Copies through original Pub/Sub metadata into:
  - attributes (best for filters), and/or
  - `meta` inside the v1 `source` (best for audit/debug)

Operational notes:

- **Idempotency**: use incoming `messageId` as `eventId` when available; otherwise generate UUID.
- **Ordering**: preserve `producedAt` from producer, keep Pub/Sub publish time separately as `publishedAt` (metadata).
- **Rollout**: create the adapter + new topics/subscriptions first, then migrate consumers to v1 topics, then migrate producers to emit v1 natively, then retire adapter.

### Alternative: consumer-side “multi-shape router” (acceptable, but increases coupling)

Change consumers to accept both:

- payload-only system event (`{service,timestamp,...}`)
- wrapped event (`{event_type, agent_name, ts, payload, ...}`) by unwrapping `payload`

Downside: every consumer re-implements compatibility logic.

### Alternative: producer dual-publish (fastest, but doubles cost/traffic)

Producers publish to both:

- legacy topic/shape
- new v1 topic/shape

Works for a short window; costlier and more failure modes.

---

## Canonical Pub/Sub Envelope v1 (application envelope)

This is the single “application-level” envelope that should be placed inside Pub/Sub `message.data` as JSON.

### Canonical fields (v1)

- **schemaVersion**: `1` (number; required)
- **eventType**: string (required; stable identifier, dot-delimited)
- **eventId**: string (required; UUID recommended; MAY reuse Pub/Sub `messageId`)
- **producedAt**: string (required; RFC3339/ISO8601 UTC recommended)
- **traceId**: string (optional but strongly recommended)
- **source**: object (required)
  - `kind`: `"service" | "agent" | "vm"` (required)
  - `name`: string (required; stable logical producer name)
  - `instanceId`: string (optional; replica/pod/revision id)
  - `meta`: object (optional; additive-only debug context)
- **payload**: object (required; event-specific contract)

### Required invariants

- `schemaVersion` increments only on breaking changes (required fields renamed/removed/meaning changed).
- Envelope field names are **camelCase** in canonical v1.
- `payload` is always a JSON object (no arrays/scalars at top level).

### Backward-compatibility aliases (accepted during transition)

When ingesting legacy shapes, map as follows:

#### From Python `EventEnvelope` (snake_case)

- `eventType` ← `event_type`
- `producedAt` ← `ts`
- `traceId` ← `trace_id`
- `source.kind` ← `"agent"` (default)
- `source.name` ← `agent_name`
- `source.meta.gitSha` ← `git_sha`
- `payload` ← `payload`
- `eventId`:
  - prefer Pub/Sub `messageId`
  - else generate UUID

#### From ops/system log record (`SystemEventPayload`, payload-only)

- `eventType`:
  - prefer payload `event_type` (or `event`), else `"system.event"`
- `producedAt` ← payload `timestamp` (best-effort; if invalid, fall back to Pub/Sub publish time)
- `source.kind` ← `"service"`
- `source.name` ← payload `service`
- `source.meta.env/version/gitSha` ← payload fields when present
- `payload` ← the entire log record object
- `eventId`:
  - prefer Pub/Sub `messageId`
  - else generate UUID

### Relationship to existing `packages/shared-types`

Canonical v1 aligns most closely with:

- `packages/shared-types/src/pubsub.ts::PubSubEvent` (it already has `eventType/schemaVersion/producedAt/source/payload`)

Additions for v1 completeness (recommended for future update to shared types; not in scope for this doc’s “no runtime changes” constraint):

- `eventId`
- `traceId`

---

## Recommended near-term contract decisions

1. **Declare Canonical Pub/Sub Envelope v1** as above (camelCase, versioned, explicit source).
2. Treat Python `EventEnvelope` (snake_case) as **legacy v0 transport** (still supported via adapter).
3. Treat system events as **payload-only** historically, but standardize that they are carried as v1 envelopes moving forward.
4. For routing, prefer `eventType` (envelope) over heuristic “payload has service+timestamp”.

---

## Action plan (documentation-only, then implementation later)

### Phase 0 (now): document + align terminology

- Publish this doc.
- Add a short note to relevant READMEs later (optional) pointing to this plan.

### Phase 1: implement adapter (shim)

- Deploy “contract adapter” that normalizes legacy inputs → v1 topics.
- Add contract tests around:
  - Python `EventEnvelope` → v1 mapping
  - `SystemEventPayload` → v1 mapping

### Phase 2: migrate consumers

- Update consumers to subscribe to v1 topics.
- Remove heuristic routing where possible; route by `eventType`.

### Phase 3: migrate producers

- Update Python publishers to emit v1 natively (and optionally still publish legacy during a short window).

### Phase 4: deprecate legacy

- Stop publishing legacy shapes.
- Remove adapter and legacy parsing code.

