## Metrics map (Pub/Sub → Cloud Run → Firestore)

This document defines a **minimal, high-signal** set of key metrics for:
- **Ingest health** (is data flowing end-to-end?)
- **Consumer lag** (is the consumer keeping up?)
- **Error rates** (is the system failing or dropping data?)

It also maps each metric to:
- **Source**: Pub/Sub, Cloud Run, Firestore
- **Collection cadence**: how often to sample/compute (typical Cloud Monitoring alignment)
- **Alert thresholds**: recommended starting **warning/critical** thresholds

### Assumptions / terminology

- **Flow**: Pub/Sub topic → Pub/Sub subscription → Cloud Run service (consumer) → Firestore writes.
- **Cadence**: Google Cloud Monitoring aligns most metrics on **60s** points. Alerts should generally evaluate over **5–15 minutes** to reduce noise.
- **Traffic-aware tuning**: thresholds below are safe defaults for steady traffic; tune per environment and expected QPS.

---

## Ingest health (end-to-end “is it working?”)

| Metric (what/why) | Source | Where to collect (Cloud Monitoring metric) | Collection cadence | Alert thresholds (warn / crit) |
|---|---|---|---:|---|
| **Ingest throughput (consumer acks per minute)** — primary “messages successfully processed” proxy | Pub/Sub | `pubsub.googleapis.com/subscription/ack_message_count` (rate, per subscription) | 60s | **Warn**: drop >50% vs 1h baseline for 10m. **Crit**: ~0 acks for 10m while publishes continue |
| **Publish throughput (messages published per minute)** — confirms upstream producer health | Pub/Sub | `pubsub.googleapis.com/topic/send_message_operation_count` (rate, per topic) | 60s | **Warn**: drop >50% vs 1h baseline for 10m. **Crit**: ~0 publishes for 10m during expected hours |
| **Backlog growth (undelivered msgs)** — early indicator of ingest/consumer issues | Pub/Sub | `pubsub.googleapis.com/subscription/num_undelivered_messages` (gauge) | 60s | **Warn**: >5,000 for 10m. **Crit**: >20,000 for 10m (or monotonic increase for 15m) |
| **Cloud Run request volume (consumer receives work)** — verifies the service is getting invoked (push) / being hit | Cloud Run | `run.googleapis.com/request_count` (rate, per service; group by `response_code_class`) | 60s | **Warn**: drop >50% vs baseline for 10m (when publishes are normal). **Crit**: ~0 requests for 10m while Pub/Sub backlog grows |
| **Firestore write throughput** — confirms persistence is happening | Firestore | `firestore.googleapis.com/document/write_count` (rate, per database) | 60s | **Warn**: drop >50% vs baseline for 10m (while requests/acks normal). **Crit**: ~0 writes for 10m while consumer is active |
| **Freshness: time since last successful ingest** — best “is data current?” signal (recommended) | Firestore (derived) | **Derived** from Firestore: scheduled query/job writes `last_ingest_ts` and exports `ingest_freshness_seconds` (custom metric) | 60s | **Warn**: >120s for 10m. **Crit**: >300s for 10m |

Notes:
- If you do not have a baseline system, replace “drop vs baseline” with absolute thresholds suitable for your expected volume.
- The freshness metric is worth adding because it’s **business-relevant** and avoids relying on indirect proxies.

---

## Consumer lag (how far behind are we?)

| Metric (what/why) | Source | Where to collect (Cloud Monitoring metric) | Collection cadence | Alert thresholds (warn / crit) |
|---|---|---|---:|---|
| **Oldest unacked message age (seconds)** — canonical consumer lag indicator | Pub/Sub | `pubsub.googleapis.com/subscription/oldest_unacked_message_age` (gauge) | 60s | **Warn**: >120s for 10m. **Crit**: >600s for 10m |
| **Undelivered message backlog** — queue depth / catch-up work remaining | Pub/Sub | `pubsub.googleapis.com/subscription/num_undelivered_messages` (gauge) | 60s | **Warn**: >5,000 for 10m. **Crit**: >20,000 for 10m |
| **Ack latency (p95/p99)** — how long messages take to be acked end-to-end | Pub/Sub | `pubsub.googleapis.com/subscription/ack_latencies` (distribution) | 60s | **Warn**: p95 > 5s for 10m. **Crit**: p95 > 20s for 10m |
| **Cloud Run concurrency saturation** — lag often starts when concurrency maxes out | Cloud Run | `run.googleapis.com/container/max_request_concurrencies` vs `run.googleapis.com/container/request_count` (or use `run.googleapis.com/container/instance_count` + request rate) | 60s | **Warn**: sustained >80% of configured concurrency for 10m. **Crit**: >95% for 10m + Pub/Sub backlog increasing |
| **Cloud Run CPU / memory utilization** — resource pressure correlates with increased lag | Cloud Run | `run.googleapis.com/container/cpu/utilizations`, `run.googleapis.com/container/memory/utilizations` | 60s | **Warn**: >80% for 10m. **Crit**: >90% for 10m (especially if lag metrics breach) |

Lag alerting guidance:
- Prefer alerting on **oldest unacked age** (time-based) over backlog size (volume-based), then use backlog as corroboration.
- Gate “lag” alerts on **expected ingest windows** (mute configs or long durations) to avoid off-hours noise.

---

## Error rates (is it failing or dropping work?)

| Metric (what/why) | Source | Where to collect (Cloud Monitoring metric) | Collection cadence | Alert thresholds (warn / crit) |
|---|---|---|---:|---|
| **Cloud Run 5xx rate** — customer-visible / platform failure indicator | Cloud Run | `run.googleapis.com/request_count` (rate) filtered to `response_code_class="5xx"`; compute 5xx% | 60s | **Warn**: 5xx% > 1% for 10m. **Crit**: 5xx% > 5% for 5m |
| **Cloud Run 4xx rate (consumer endpoints)** — often indicates bad payloads, auth, schema issues | Cloud Run | `run.googleapis.com/request_count` filtered to `response_code_class="4xx"`; compute 4xx% | 60s | **Warn**: 4xx% > 2% for 10m. **Crit**: 4xx% > 10% for 10m |
| **Application error logs** — catches non-HTTP failures (parsing, write errors, partial failures) | Cloud Run | Log-based metric from Cloud Logging: `severity>=ERROR` (optionally filter `jsonPayload.service="<service>"`) | 60s | **Warn**: >5 errors/min for 10m. **Crit**: >20 errors/min for 5m |
| **Pub/Sub nack rate** — consumer explicitly failed messages | Pub/Sub | `pubsub.googleapis.com/subscription/nack_message_count` (rate) | 60s | **Warn**: nack% > 0.5% for 10m. **Crit**: nack% > 2% for 10m |
| **Dead-letter messages (DLQ) rate** — definitive “messages are being dropped/parked” | Pub/Sub | `pubsub.googleapis.com/subscription/dead_letter_message_count` (rate, per subscription) | 60s | **Warn**: >0 for 10m. **Crit**: >10/min for 5m |
| **Firestore request errors** — persistence-layer failures | Firestore | `firestore.googleapis.com/api/request_count` (rate) grouped by status / response code (if available) | 60s | **Warn**: error% > 0.5% for 10m. **Crit**: error% > 2% for 10m |
| **Firestore write latency (p95)** — slow writes can cause timeouts, retries, lag | Firestore | `firestore.googleapis.com/api/request_latencies` (distribution) filtered to write methods (if available) | 60s | **Warn**: p95 > 500ms for 10m. **Crit**: p95 > 2s for 10m |

---

## Recommended alert wiring (quiet + actionable)

- **Page (critical)**:
  - Pub/Sub `oldest_unacked_message_age` critical breach
  - Cloud Run 5xx critical breach
  - DLQ rate > 0 (sustained)
  - “Freshness” critical breach (if implemented)
- **Ticket (warning)**:
  - Backlog size warning breach
  - Cloud Run CPU/memory sustained high
  - Firestore p95 latency warning breach

### Practical defaults for evaluation windows

- **Warn**: 10m evaluation window (requires sustained issue)
- **Crit**: 5–10m evaluation window depending on blast radius

If you already maintain runbooks, link alerts to the relevant `docs/ops/runbooks/*` entry (or add one per alert class).
