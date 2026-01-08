# Firestore write profile: `cloudrun_consumer/` (Cloud Run Pub/Sub → Firestore)

This note profiles **Firestore writes performed by `cloudrun_consumer/`** (the FastAPI service in `cloudrun_consumer/main.py`) and provides **write-rate estimates per topic**, **hot-document identification**, and **batching/aggregation recommendations**.

## What `cloudrun_consumer` writes (by collection/document)

`cloudrun_consumer` currently routes only **system-event shaped payloads** (see `cloudrun_consumer/schema_router.py`) and writes:

- **Idempotency marker**
  - **Path**: `ops_dedupe/{messageId}`
  - **Operation**: `create()` inside a Firestore transaction
  - **Purpose**: treat Pub/Sub at-least-once delivery as “exactly-once” for materialization
  - **Fields**: `createdAt` (server timestamp), `messageId`

- **Latest service state projection**
  - **Path**: `ops_services/{serviceId}`
  - **Operation**: `set()` inside the same transaction
  - **Purpose**: “latest-only” read model for an ops dashboard
  - **Fields**: `serviceId`, `env`, `status`, `lastHeartbeatAt`, `version`, `region`, `updatedAt`, `source{topic,messageId,publishedAt}`

### Writes per Pub/Sub message (important for sizing)

For each Pub/Sub message that is **first-seen** (i.e., not a duplicate):

- **2 document writes** (within 1 transaction):
  - 1x create `ops_dedupe/{messageId}`
  - 1x set `ops_services/{serviceId}`

For duplicates:

- **0 writes** (the dedupe doc already exists, so the transaction returns a no-op)

For stale/out-of-order messages:

- **1 write**: the dedupe doc is created, then the service doc update is skipped (“stale_event_ignored”)

> Note: the transaction also performs reads (`ops_dedupe/{messageId}` and `ops_services/{serviceId}`), which can matter for latency/lock contention, but this doc focuses on write rates.

## Topics handled by `cloudrun_consumer` (and estimated write rates)

### Topic: `SYSTEM_EVENTS_TOPIC` (example value: `system.events`)

**Current reality**: `cloudrun_consumer` does not infer the topic from the Pub/Sub push envelope (push payloads include the subscription, not the topic). Instead it records `source.topic` from env var `SYSTEM_EVENTS_TOPIC`. Operationally, this is a **single-topic consumer** today.

#### Write-rate model (per topic)

Let:

- \(S\) = number of distinct `serviceId` values producing events
- \(T\) = average event period per service (seconds), e.g. heartbeat every 30s → \(T=30\)
- \(R\) = message rate for the topic (messages/sec) = \(S / T\)
- \(W\) = Firestore write rate (writes/sec)

Then (assuming events are mostly first-seen and not stale):

- **\(W \approx 2R = 2S/T\)** writes/sec

If you expect some staleness/out-of-order, use:

- **\(W \approx (2\cdot p_{applied} + 1\cdot p_{stale})\cdot R\)**, where \(p_{applied}+p_{stale}+p_{duplicate}=1\)

#### Concrete sizing examples

| Services (S) | Period (T) | Topic msg rate R (=S/T) | Approx writes/sec W (=2R) | Approx writes/min |
|---:|---:|---:|---:|---:|
| 25 | 60s | 0.42/s | 0.83/s | 50 |
| 50 | 30s | 1.67/s | 3.33/s | 200 |
| 100 | 30s | 3.33/s | 6.67/s | 400 |
| 200 | 10s | 20.0/s | 40.0/s | 2,400 |
| 500 | 10s | 50.0/s | 100.0/s | 6,000 |

Interpretation:

- The **dominant write driver** is heartbeat/event cadence multiplied by number of services.
- The **dedupe marker doubles write volume** for first-time deliveries.

## Hot documents / contention risks

### 1) `ops_services/{serviceId}` is the hot-document risk

All events for the same `serviceId` converge on a **single document**. This becomes hot when:

- Multiple instances emit heartbeats under the same `serviceId` (e.g., each replica reports separately)
- Heartbeat cadence is aggressive (sub-10s) for many services
- Message ordering is noisy, increasing transactional retries and stale rejections

Firestore has **per-document update throughput limits** and transactions amplify contention (read + write under transaction semantics). Symptoms when this becomes hot:

- Elevated p95/p99 write latency
- Increased aborted/retried transactions
- CPU spikes in the Cloud Run consumer due to retries/backoff

### 2) `ops_dedupe/{messageId}` is not a “hot doc”, but it is a write-amplifier and growth risk

Each message writes a unique document, so there’s no single-document hotspot. However:

- It is **1 extra write per message** (and one extra read in the transaction)
- The collection grows **unbounded** unless you apply TTL/retention
- It adds extra index/storage overhead proportional to message volume

## Recommendations (batching / aggregation / retention)

### A) If `ops_services/{serviceId}` write contention is expected

Choose one of these patterns (ordered from simplest → most scalable):

- **Debounce writes (time-based coalescing)**: only update `ops_services/{serviceId}` at most once every N seconds per service, while still processing events. This keeps UI “near-realtime” while bounding document write rate.
- **Write only on material change**: if an event doesn’t change `status/version/region` and only advances timestamps within a small window, skip the Firestore update.
- **Split by producer instance, then aggregate**:
  - Write per-instance docs like `ops_services/{serviceId}/instances/{instanceId}` (higher fanout, no single hot doc)
  - Maintain a separate aggregated “latest” doc (or compute aggregation client-side if acceptable)

### B) Consider whether the dedupe marker is worth its cost

If occasional duplicates are acceptable (i.e., rewriting the same service state is not harmful), you can often **drop `ops_dedupe`** and rely on idempotent upserts + stale protection only. That would roughly **halve writes** for first-time deliveries.

If you keep dedupe:

- **Add TTL / retention** for `ops_dedupe` (recommended)
  - Add an `expiresAt` timestamp field and configure Firestore TTL on it
  - Pick a retention window that matches your retry/DLQ replay horizon (commonly 1–7 days)
- **Minimize payload** stored in dedupe docs (currently already minimal)

### C) Improve ordering to reduce stale/transaction churn

If the producer can set Pub/Sub ordering keys (e.g., `ordering_key = serviceId`), you can reduce out-of-order delivery per service. With reliable ordering, you may be able to **simplify stale protection** and reduce transaction retries.

### D) Observability checklist (to validate assumptions quickly)

Track these to confirm whether batching/aggregation is needed:

- **Write volume**: Firestore writes/sec by collection (`ops_services`, `ops_dedupe`)
- **Hot keys**: top `serviceId` by update frequency (can be inferred from logs + `serviceId`)
- **Transaction retries/aborts**: elevated retry rates indicate contention on `ops_services/{serviceId}`
- **Stale rejection rate**: fraction of events returning `stale_event_ignored` (suggests ordering issues)

## Notes / scope caveats

- `cloudrun_consumer/handlers/ingest_health.py` exists but is **not wired into routing** in `cloudrun_consumer/schema_router.py` today, so it does not contribute to Firestore write volume for this service.
- Other parts of the repo contain similar “materializer” services that handle additional projections/topics (e.g., `backend/ops_dashboard_materializer`), but they are **out of scope** for this profile, which is specifically `cloudrun_consumer/`.

