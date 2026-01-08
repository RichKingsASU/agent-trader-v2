# Consumer safety check: `cloudrun_consumer/`

## Verdict: **NEEDS_PATCH**

Idempotency for the current (reachable) event path is generally well-designed, but there are **material Firestore reliability risks**:

- **Potential data loss / clobbering**: writes use full-document `set()` (no merge) and stale protection only compares timestamps, not field-level concurrency.
- **Hot-spot risk**: a single document (`ops_services/{serviceId}`) is repeatedly overwritten; high-frequency service heartbeats can concentrate writes on a small number of docs.
- **Operational risk**: the dedupe store (`ops_dedupe`) has **unbounded growth** (no TTL/cleanup path in this repo).

No code changes were made as requested; this is an inspection + recommendations document.

---

## Scope & entrypoints inspected

### Reachable runtime path (today)

- `cloudrun_consumer/main.py` receives Pub/Sub push messages at `POST /pubsub/push`
- Routes payloads via `cloudrun_consumer/schema_router.py`
- Currently routes only to `handlers/system_events.py:handle_system_event`
- Firestore writes go through `cloudrun_consumer/firestore_writer.py`

### Unreachable / stale module present

`handlers/ingest_health.py` appears to be **unused** (not imported by `schema_router.py`) and also references symbols/methods that do not exist in this folder (`SourceContext`, `EventContext`, `upsert_ingest_pipeline`, and `FirestoreWriter()` without required args). It is therefore **not an active write path**, but if later wired in it would require a new safety review.

---

## Idempotency strategy (verification)

### What it does

For the system-events path, idempotency is implemented using Pub/Sub `messageId`:

- On each message, the consumer attempts to create a Firestore document:
  - `ops_dedupe/{messageId}`
- The create is executed inside a Firestore transaction via `txn.create(...)`
  - If the dedupe doc already exists, processing is treated as a **duplicate no-op**
  - This is appropriate for Pub/Sub push’s **at-least-once** delivery semantics

### Strengths

- **Correct primitive**: using `create()` (not `set(merge=True)`) is a strong dedupe signal because it fails if the doc already exists.
- **Transactional**: dedupe and the materialization write are in the same transaction (`dedupe_and_upsert_ops_service`), so you do not get “wrote the read-model but failed to mark dedupe” or vice versa due to partial failures inside Firestore.

### Gaps / assumptions

- **Dedupe key is only `messageId`**, not namespaced by topic/subscription:
  - Today, this service appears to process only system events (single routing path).
  - If in the future multiple topics/subscriptions are routed through the same consumer, consider scoping the dedupe key by `(topic, subscription, messageId)` to eliminate cross-stream collision risk (even if collision probability is low).
- **Dedupe retention** is not managed here:
  - `ops_dedupe` will grow without bound unless there is an external TTL policy, scheduled cleanup, or Firestore TTL configured on `createdAt`.

---

## Firestore write paths (reachable)

There are exactly **two** Firestore document write targets in the reachable path:

1. **Idempotency record**
   - **Collection/doc**: `ops_dedupe/{messageId}`
   - **Operation**: transactional `create`
   - **Payload**: `{ createdAt: SERVER_TIMESTAMP, messageId: <string> }`

2. **Service status read model**
   - **Collection/doc**: `ops_services/{serviceId}`
   - **Operation**: transactional `set` (full-document overwrite)
   - **Payload** (always rewritten):
     - `serviceId, env, status, lastHeartbeatAt, version, region, updatedAt`
     - `source: { topic, messageId, publishedAt }`

---

## Risk analysis (per requested categories)

### 1) Firestore writes that could **overwrite newer data**

#### A. Full-document overwrite (`txn.set`) can clobber unrelated fields

`ops_services/{serviceId}` is written with `txn.set(service_ref, doc)` (no merge).

Implications:

- If **any other writer** (another service, backfill job, manual patch, future schema expansion) adds fields to `ops_services/{serviceId}`, this consumer will **delete/overwrite** those fields on the next write, even if that other write is “newer” in intent.
- Stale protection only guards against older `updated_at` relative to the existing `lastHeartbeatAt/updatedAt`. It does **not** guard against overwriting fields outside those comparisons.

Why this matters:

- This is a common failure mode in “read-model materializers” when multiple producers evolve.
- Even with perfect timestamp ordering, full overwrites can still lose data.

#### B. Tie-break behavior: equal timestamps overwrite

Stale protection is `incoming < existing_max` → ignore; otherwise apply. If two events have the same effective `updatedAt`, whichever arrives later will overwrite.

This is typically acceptable if `updatedAt` is strictly monotonic per `serviceId`, but if producers emit identical timestamps (e.g., coarse resolution, clock rounding), you can get non-deterministic last-write-wins.

#### C. If stored timestamps become unparseable, stale protection degrades

Stale protection depends on parsing stored `lastHeartbeatAt` / `updatedAt`. If those fields were ever written in an unexpected format (e.g., numeric epoch, malformed string), parsing may yield `None`, causing the consumer to treat the doc as having no “existing_max” and apply overwrites without stale protection.

---

### 2) Firestore writes that could **amplify duplicates**

**Current reachable path looks safe**:

- Duplicate Pub/Sub deliveries of the same message (same `messageId`) become a **no-op** because `ops_dedupe/{messageId}` already exists.
- There are no array-appends, increments, or “append-only” patterns in the reachable path that would magnify duplicates.

Edge condition worth noting:

- `ensure_message_once()` returns “first time” if `message_id` is empty, but the HTTP handler rejects missing `messageId` with a 400, so this should not happen in production for the reachable path.

---

### 3) Firestore writes that could **hot-spot documents**

#### A. `ops_services/{serviceId}` is inherently a hot document under frequent updates

Each service emits repeated system events; those all map to the same document ID (`serviceId`). This concentrates writes.

Risks:

- Firestore has practical per-document write throughput limits; frequent heartbeats across a small set of services can cause contention, latency spikes, or transaction aborts/retries.
- The design is “current status by key”, which is convenient for reads but must be sized carefully for write QPS.

Mitigations (design-level, not implemented here):

- Reduce write frequency (debounce / coalesce).
- Use sharded documents or time-bucketed writes if you need high-frequency telemetry.
- Keep `ops_services` as “latest pointer” but write high-rate events into an append-only collection keyed by time bucket.

#### B. `ops_dedupe/{messageId}` is *not* a hot-spot (good distribution)

Document IDs are effectively random/uniform (`messageId`), so writes should distribute across many documents/partitions. The issue here is not hot-spotting but retention.

---

## Recommendations (no code changes performed)

To reach a “PASS” for backend reliability safety, consider:

- **Avoid clobbering**: switch `ops_services/{serviceId}` writes to `set(..., merge=True)` or `update(...)` with explicit field set, and treat “schema-owned” fields carefully.
- **Strengthen concurrency guard**: enforce compare-and-set semantics against a stored `updatedAt` (and/or store a monotonic sequence) so equal-timestamp reorders don’t overwrite unpredictably.
- **Plan dedupe retention**: configure Firestore TTL on `ops_dedupe.createdAt` or add an external cleanup process; otherwise storage grows without bound.
- **Hot-spot planning**: validate expected event rates per `serviceId`; if high, introduce aggregation/sharding patterns.

---

## Summary

- **Idempotency**: Implemented correctly for Pub/Sub at-least-once using transactional `ops_dedupe/{messageId}` creation.  
- **Overwrite risk**: Present due to full-document overwrites (`txn.set` without merge) and timestamp-only stale protection.  
- **Duplicate amplification**: No issues in the reachable path.  
- **Hot-spot risk**: Present for `ops_services/{serviceId}` if event volume per service is high.  

