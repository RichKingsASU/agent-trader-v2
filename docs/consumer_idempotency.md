## `cloudrun_consumer` idempotency + stale-event analysis

Scope: inspect `cloudrun_consumer/` (Cloud Run Pub/Sub push → Firestore materializer). This document enumerates **all Firestore writes in this service**, verifies the **idempotency guarantees**, proposes **deterministic document IDs**, and describes the current and recommended **stale-event handling** strategy.

Non-goals: code changes, implementation details, producer changes.

## Architecture summary

- **Ingress**: `POST /pubsub/push` (Pub/Sub push envelope).
- **Decode**: base64 → JSON object payload.
- **Routing**: only “system event shaped” payloads are routed (currently `handlers/system_events.py`).
- **Materialization**:
  - **Dedupe** by Pub/Sub `messageId` using `ops_dedupe/{messageId}`.
  - **Stale protection** for service state using a timestamp guard before writing `ops_services/{serviceId}`.

## 1) All Firestore writes (inventory)

### Writes executed on the active request path

The current request path (via `main.py` → `schema_router.py` → `handlers/system_events.py` → `firestore_writer.py`) performs exactly these Firestore writes:

- **`ops_dedupe/{messageId}`**
  - **Operation**: `txn.create(dedupe_ref, {...})`
  - **Purpose**: “exactly-once” effect for an at-least-once Pub/Sub push delivery
  - **Fields written** (logical):
    - `createdAt = SERVER_TIMESTAMP`
    - `messageId = <pubsub messageId>`

- **`ops_services/{serviceId}`**
  - **Operation**: `txn.set(service_ref, doc)`
  - **Purpose**: upsert/overwrite a “read model” document representing current service health
  - **Fields written** (logical):
    - `serviceId, env, status, lastHeartbeatAt, version, region, updatedAt`
    - `source: { topic, messageId, publishedAt }`

### Firestore reads (relevant because they influence idempotency/staleness)

Inside the same Firestore transaction used for the writes above:

- **Read** `ops_dedupe/{messageId}` to detect duplicates
- **Read** `ops_services/{serviceId}` to apply stale-event logic

### Firestore write methods not used

No usage found in `cloudrun_consumer/` of:

- `update`, `delete`, `batch.commit`, `bulk_writer`, `collection.add()`, array transforms, or field increments.

### Note: an apparently orphaned handler file

`cloudrun_consumer/handlers/ingest_health.py` references symbols that do not exist in this package (`SourceContext`, `EventContext`, `upsert_ingest_pipeline`) and is not imported by the router. As written, it is **not on the execution path** and its Firestore effects cannot be validated from this package alone.

## 2) Verified idempotency guarantees (what is and is not guaranteed)

### What the service guarantees today (given Pub/Sub push semantics)

Pub/Sub push delivery is **at-least-once**; Cloud Run may receive duplicates and concurrent deliveries.

This consumer provides **idempotent effects per Pub/Sub message**:

- **Deduplication key**: `messageId` from the Pub/Sub envelope (required; requests without it are rejected).
- **Exactly-once effect (per messageId)**:
  - In a single Firestore transaction, the consumer:
    - checks whether `ops_dedupe/{messageId}` exists
    - if missing, creates it with `txn.create(...)` (fails if it already exists)
    - only then applies the state write to `ops_services/{serviceId}`
  - Because both writes are in one transaction, the consumer gets an atomic “claim + apply” behavior:
    - either the message is claimed and applied once, or it is not claimed at all
    - duplicates become a no-op after the first successful commit

Pseudocode (current behavior, simplified):

```text
function process_pubsub_push(messageId, payload):
  serviceId = payload.service
  updatedAt = coalesce(payload.producedAt, payload.publishedAt, payload.timestamp, pubsub.publishTime)

  txn:
    if exists(doc("ops_dedupe", messageId)):
      return {applied:false, reason:"duplicate_message_noop"}

    create(doc("ops_dedupe", messageId), {createdAt: SERVER_TIMESTAMP, messageId: messageId})

    existing = get(doc("ops_services", serviceId))
    existingMax = max(existing.lastHeartbeatAt, existing.updatedAt)
    if existingMax != null and updatedAt < existingMax:
      return {applied:false, reason:"stale_event_ignored"}  // dedupe already claimed

    set(doc("ops_services", serviceId), { ...fields..., updatedAt: updatedAt, source:{...} })
    return {applied:true, reason:"applied"}
```

### What is *not* guaranteed today

- **Not “exactly-once per logical event”** if the same logical event can be republished with a different Pub/Sub `messageId`.
  - Current dedupe uses only `messageId`, which is stable for retries of the *same* Pub/Sub message, but not across independent publishes.
- **Not deterministic ordering when timestamps tie**.
  - Stale protection uses only `incoming < existingMax`. If timestamps are equal, the later-processed event wins, which can be nondeterministic under concurrency.
- **Retention/cleanup of dedupe records is unspecified**.
  - `ops_dedupe` will grow without a TTL policy; long-term, this becomes operational risk (storage + index bloat).

## 3) Proposed deterministic document IDs

This section proposes deterministic IDs to (a) avoid collisions, (b) make idempotency independent of Pub/Sub transport details, and (c) support traceability.

### `ops_services` document ID

Current:

- `ops_services/{serviceId}` where `serviceId = payload.service`

Risk:

- If multiple environments share a Firestore database, `serviceId` alone can collide (e.g., `prod` and `staging` both have a `strategy-engine` service).

Recommendation:

- **Include `env` in the doc ID** (and optionally region if you run per-region instances):

```text
serviceDocId = normalize(env) + "__" + normalize(serviceId)
// optionally: + "__" + normalize(region)
```

### `ops_dedupe` document ID (dedupe key)

Current:

- `ops_dedupe/{messageId}`

What this is good for:

- **Transport-level** dedupe for Pub/Sub redelivery of the same message.

Recommendation (two-tier approach):

- Keep transport-level dedupe (cheap and already correct).
- Add a **logical-event dedupe key** (deterministic across republishes) when/if payloads can be retried by re-publishing:

```text
if payload has stable eventId:
  logicalKey = payload.eventId
else:
  logicalKey = sha256_base32(
    canonical_json({
      "schema": payload.schemaVersion or "unknown",
      "type": payload.eventType or "system_event",
      "service": payload.service,
      "producedAt": payload.producedAt or payload.timestamp or "",
      "region": payload.region or "",
      // include only fields that define identity, not derived/transient fields
    })
  )[0:52]  // shortened for Firestore id limits; collision risk acceptable if low

dedupeDocId = normalize(env) + "__" + logicalKey
```

Notes:

- Firestore doc IDs have length limits; use a compact encoding (base32/base64url) and truncate.
- Canonicalization must be deterministic (sorted keys, stable formatting).
- If you adopt logical-key dedupe, you can still store `messageId` for traceability in the dedupe document.

## 4) Stale-event handling strategy

### Current strategy (implemented)

The consumer protects `ops_services/{serviceId}` from out-of-order events using a **timestamp guard**:

- Compute `updatedAt` for the incoming event:
  - `updatedAt = producedAt || publishedAt || payload.timestamp || pubsub.publishTime`
- Read existing doc and compute:
  - `existingMax = max(existing.lastHeartbeatAt, existing.updatedAt)`
- Apply rule:
  - if `existingMax != null` and `incoming.updatedAt < existingMax`: **ignore** as stale
  - else: **overwrite** the document

Properties:

- **Out-of-order tolerance**: older events won’t overwrite newer state (as long as timestamps are comparable).
- **Convergent state**: repeated delivery converges to the same “latest timestamp wins” document.
- **Clock sensitivity**: correctness depends on producer timestamps not being badly skewed.

### Recommended strategy (more deterministic + more robust)

If you want stronger determinism under concurrency and resilience to timestamp skew:

- **Ordering key**: compare a tuple rather than a single timestamp:
  - primary: `updatedAt` (event time)
  - tie-breaker: `source.publishedAt` (Pub/Sub time) or `source.messageId`
  - best: a producer-issued monotonic `sequence` per service instance

Pseudocode (recommended ordering):

```text
incomingKey = (updatedAt, payload.sequence or null, pubsub.publishTime, messageId)
existingKey = (existing.updatedAt, existing.sequence or null, existing.source.publishedAt, existing.source.messageId)

if existingKey != null and incomingKey < existingKey:
  ignore stale
else:
  apply overwrite
```

Operationally recommended complements:

- **Dedupe TTL**:
  - Add a TTL field (e.g., `expireAt = now + 7d`) to dedupe docs and enable Firestore TTL policy on that field.
  - This bounds `ops_dedupe` growth while preserving retry windows.
- **Observability for staleness**:
  - Count `stale_event_ignored` outcomes and alert on spikes (often indicates clock issues or duplicated pipelines).

## Summary table (current guarantees)

- **Writes**
  - `ops_dedupe/{messageId}` via `txn.create(...)`
  - `ops_services/{serviceId}` via `txn.set(...)`
- **Idempotency**
  - **Guaranteed**: exactly-once *effects* per Pub/Sub `messageId` (within Firestore transaction semantics)
  - **Not guaranteed**: exactly-once per logical event across re-publishes with new `messageId`
- **Stale handling**
  - **Implemented**: last-write-wins by `updatedAt` with guard `incoming < max(existing.lastHeartbeatAt, existing.updatedAt)`
  - **Recommended**: tuple ordering with tie-breakers and/or producer sequence to eliminate nondeterministic ties

