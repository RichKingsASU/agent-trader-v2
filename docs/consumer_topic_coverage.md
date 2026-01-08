# Consumer topic coverage (Cloud Run Pub/Sub → Firestore)

This document inspects the current `cloudrun_consumer/` service and proposes handler designs for additional Pub/Sub topics.

## What exists today in `cloudrun_consumer`

### Entry point and envelope handling

`cloudrun_consumer/main.py` exposes `POST /pubsub/push` (Cloud Run Pub/Sub push subscription format).

Processing flow:

- Parse request JSON and validate Pub/Sub push envelope
  - Requires `message.messageId` and `message.data` (base64)
  - Parses `message.publishTime` into a UTC `datetime`
- Decode `message.data` as UTF-8 JSON and require the decoded payload to be an object (`dict`)
- Route payload to a handler using `cloudrun_consumer/schema_router.py` (shape-based routing)
- Call the routed handler and write to Firestore
- Error behavior:
  - `ValueError` raised by handler ⇒ HTTP **400** (treat as poison; DLQ-friendly)
  - Any other exception ⇒ HTTP **500** (Pub/Sub retries)

**Important constraint:** Pub/Sub push includes the *subscription* but not the *topic*. This service currently works around that by injecting a single topic name via env var and passing it as `source_topic`.

### How “system-events” are handled

Current routing: `schema_router.route_payload()` routes to `handlers/system_events.py` when the decoded payload looks like a system event:

- `payload["service"]` is a non-empty string
- `payload["timestamp"]` exists (any non-`None` value)

Handler behavior (`handlers/system_events.py`):

- **Target read model**: `ops_services/{serviceId}`
- **Idempotency**: transactional “message once” dedupe using Pub/Sub `messageId`
  - Creates `ops_dedupe/{messageId}` in the same Firestore transaction
  - If it already exists, returns a no-op: `duplicate_message_noop`
- **Stale-event protection**: reject out-of-order writes
  - Computes `updated_at = producedAt || publishedAt || timestamp || pubsub.publishTime`
  - Only applies the write if `updated_at >= max(existing.lastHeartbeatAt, existing.updatedAt)`
  - If stale, returns `stale_event_ignored` (and note: the dedupe doc has already been created, so retries won’t reapply it)
- **Fields written** (overwrite semantics):
  - `serviceId, env, status, lastHeartbeatAt, version, region, updatedAt`
  - `source: { topic, messageId, publishedAt }`

### Notable repo hygiene observation

`cloudrun_consumer/handlers/ingest_health.py` appears **unused** (not referenced by `schema_router.py`) and out of sync with current `firestore_writer.py` / `schema_router.py` types. It does not affect current behavior.

## Proposed topic handler designs

These designs assume the producer payloads follow the repo’s canonical envelope:

- `backend/messaging/envelope.py` (`EventEnvelope`):
  - `event_type` (string)
  - `agent_name`, `git_sha`
  - `ts` (producer timestamp string)
  - `payload` (object)
  - `trace_id`

This matches existing producers such as `backend/streams/alpaca_bars_ingest.py`, which publishes to topic `market-bars-1m` with `event_type` defaulting to `market.bars.1m` and bar fields in `payload` (`symbol,timeframe,ts,open,high,low,close,volume,source`).

### Topic coverage summary (proposed)

| Pub/Sub topic | Expected `event_type` | Target Firestore collection | Idempotent doc ID strategy | Stale-event handling |
|---|---|---|---|---|
| `market-ticks` | `market.ticks` (or `market.tick`) | `market_ticks_latest` | `docId = <symbol>` | Apply only if incoming tick time is newer (see below) |
| `market-bars-1m` | `market.bars.1m` | `market_bars_1m` | `docId = <symbol>__<minute_start_utc_iso>` | Apply only if newer revision for that minute (publishTime / producedAt ordering) |
| `trade-signals` | `trade.signal` (or `trade.signals`) | `trade_signals` | `docId = <signalId>` else deterministic hash | Apply only if incoming state transition is newer (updatedAt / publishedAt ordering) |

> Naming note: collections are proposed as snake_case to match existing `ops_services`, `ops_dedupe`. If there is an established naming convention elsewhere (e.g., `marketDataBars1m`), these can be adjusted without changing the strategies below.

---

## Handler: `market-ticks`

### Target Firestore collection

- **Collection**: `market_ticks_latest`
- **Document**: one document per symbol
  - `market_ticks_latest/{symbol}`

Rationale: per-tick persistence in Firestore is typically cost/throughput prohibitive; a “latest tick” read model aligns with Firestore’s strengths (fast key lookup / UI dashboards / lightweight consumers).

### Idempotent doc ID strategy

- **Doc ID**: `symbol` (canonicalized; e.g. uppercase `SPY`, `AAPL`)

This makes updates naturally idempotent for retries and duplicates: writing the same tick repeatedly converges on the same state doc.

### Stale-event handling

Treat “stale” as *out-of-order tick updates* for the same symbol.

- **Event time source (best → fallback)**:
  - `envelope.payload.ts` (if it’s the tick timestamp)
  - else `envelope.ts`
  - else Pub/Sub `publishTime`
- **Ordering rule**:
  - Compute an `effective_ts` and only overwrite if `effective_ts` is **strictly newer** than stored `lastTickAt`
  - If ties can happen (same `effective_ts`), use a tie-breaker if present:
    - prefer a monotonic `sequence` / `seq` in payload
    - else prefer newer Pub/Sub `publishTime`

**Age-based late drop (optional but recommended):**

- If `effective_ts < now() - MAX_LATE_AGE` (e.g. 15 minutes), ignore as `too_old_ignored`
  - This prevents backfills or clock-skew events from thrashing a “latest” read model.

### Suggested document shape (read model)

- `symbol`
- `lastTickAt` (timestamp)
- `price`, `bid`, `ask`, `size` (as available)
- `source: { topic, messageId, publishedAt, producer: { agent_name, git_sha, trace_id } }`

---

## Handler: `market-bars-1m`

### Target Firestore collection

Two reasonable options; pick based on query patterns:

**Option A (time series in a flat collection):**

- **Collection**: `market_bars_1m`
- **Doc ID**: `symbol__<minute_start_utc_iso>`
  - Example: `SPY__2026-01-08T14:32:00Z`

**Option B (partitioned by symbol/day for operational scalability):**

- **Collection**: `market_bars_1m_by_symbol`
- **Doc path**:
  - `market_bars_1m_by_symbol/{symbol}/days/{YYYYMMDD}/minutes/{HHMM}`

This doc focuses on Option A because the task asks for a single “target collection”, but Option B is often operationally easier for large backfills and per-symbol scans.

### Idempotent doc ID strategy

- **Doc ID** (Option A): `f"{SYMBOL}__{minute_start_iso_z}"`
  - `SYMBOL`: canonicalized symbol (e.g. uppercase)
  - `minute_start_iso_z`: the bar timestamp truncated to the minute in UTC (e.g. `2026-01-08T14:32:00Z`)

This mirrors existing producer semantics:

- `backend/streams/alpaca_bars_ingest.py` emits `payload.ts` already aligned to the minute (seconds/micros zeroed in synthetic mode).

### Stale-event handling

Bars can be:

- **Immutable** (final bar per minute): duplicates are harmless.
- **Corrected** (same minute updated later): consumer must accept “newer revision” updates.

Recommended rule for correctness with minimal producer coupling:

- Define `bar_key_ts = minute_start(payload.ts)` (UTC)
- Compute `effective_revision_ts` using (best → fallback):
  - `payload.producedAt` (if present and parseable)
  - else `envelope.ts`
  - else Pub/Sub `publishTime`
- Only apply an upsert if `effective_revision_ts` is **newer** than the stored `source.revisionAt` (or `source.publishedAt` if you keep only Pub/Sub time)
  - If not newer ⇒ `stale_event_ignored`

**Age-based late drop (optional):**

- If `bar_key_ts < now() - MAX_BACKFILL_AGE` (e.g. 7 days) and the consumer is intended for “recent” read models only, ignore as `too_old_ignored`.
  - If historical backfill is required, disable this drop and instead rely on the per-minute doc ID + revision ordering.

### Suggested document shape

Store the canonical OHLCV fields plus provenance:

- `symbol`
- `timeframe` (e.g. `"1m"`)
- `ts` (minute start)
- `open, high, low, close, volume`
- `source: { topic, messageId, publishedAt, revisionAt, producer: { agent_name, git_sha, trace_id } }`

---

## Handler: `trade-signals`

### Target Firestore collection

- **Collection**: `trade_signals`
- **Document**: one document per logical signal
  - `trade_signals/{signalId}`

Rationale: trade signals often have a lifecycle (created → acknowledged → executed/cancelled). A single stable document supports idempotent updates and easy UI consumption.

### Idempotent doc ID strategy

Preferred: producer supplies a stable identifier.

- **Use** `payload.signalId` (or `payload.id`, `payload.dedupeKey`, `payload.fingerprint`) if present and non-empty.

Fallback: deterministic hash (stable across retries and duplicates) computed from fields that define “the same signal”:

- Example basis:
  - `strategyId`
  - `symbol`
  - `timeframe`
  - `side` / `action` (BUY/SELL/etc.)
  - `decisionAt` (or `envelope.ts`)
  - `modelVersion` / `git_sha` (optional; include only if you want different versions to produce distinct signals)

### Stale-event handling

Two stale cases matter:

1) **Out-of-order lifecycle updates** for the same `signalId` (e.g., “executed” arrives before “created” due to retries or multi-producer races).
2) **Duplicate deliveries** of the exact same update.

Recommended rule:

- Define `effective_update_ts` using (best → fallback):
  - `payload.updatedAt` (if present and parseable)
  - else `payload.decisionAt` (if that represents creation time)
  - else `envelope.ts`
  - else Pub/Sub `publishTime`
- Only apply an upsert if `effective_update_ts` is **newer** than stored `updatedAt` (or stored `source.publishedAt` if you don’t have an app-level timestamp)
  - Otherwise ⇒ `stale_event_ignored`

If you support explicit lifecycle ordering via a monotonic integer:

- Prefer `payload.sequence` / `payload.version` over timestamps for stale checks:
  - apply only if `incoming.sequence > stored.sequence`

### Suggested document shape

- Identity:
  - `signalId`, `strategyId`, `symbol`, `timeframe`
- Decision:
  - `action`/`side`, `confidence`, `reason`, `price`, `targets`, `risk`
- Lifecycle:
  - `state` (e.g. `new|ack|executed|cancelled|expired`)
  - `createdAt`, `updatedAt`
- Provenance:
  - `source: { topic, messageId, publishedAt, producer: { agent_name, git_sha, trace_id } }`

---

## Cross-cutting implementation notes (for future work)

### Routing: topic/subscription awareness

Because Pub/Sub push does **not** include the topic name, a multi-topic materializer needs one of these patterns:

- **Per-subscription deployment**: one Cloud Run service per subscription, configured with a single `SOURCE_TOPIC` env var (similar to today’s `SYSTEM_EVENTS_TOPIC`).
- **Routing table by subscription** (recommended): configure `subscription → {kind, topic}` in env, similar to `backend/ops_dashboard_materializer`’s `DASHBOARD_MATERIALIZER_ROUTES_JSON`.

For the new topics, routing by `event_type` alone is not sufficient if multiple topics can emit the same `event_type`, and it doesn’t solve populating `source.topic`.

### Idempotency: messageId vs deterministic doc IDs

Current `cloudrun_consumer` uses a **messageId dedupe collection** (`ops_dedupe/{messageId}`) *plus* stale checks for `ops_services`.

For the proposed topics:

- **Latest-state docs** (`market_ticks_latest/{symbol}`) can be made safe with stale checks alone (message duplicates overwrite the same doc), but a dedupe collection can reduce write load if needed.
- **Per-minute bars** (`market_bars_1m/{symbol__minute}`) are naturally idempotent by doc ID; stale checks matter only if corrections are expected.
- **Signals** (`trade_signals/{signalId}`) should be deterministic by doc ID; stale checks prevent lifecycle regression.

### Poison vs transient failures

Keep the existing contract:

- Validation/schema errors for a specific event ⇒ **400** (poison/DLQ)
- Firestore/API/transient errors ⇒ **500** (retry)

