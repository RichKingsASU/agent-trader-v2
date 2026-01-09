## Cloud Run Pub/Sub → Firestore Materializer (Phase 1)

Phase 1 scope: **system events → `ops_services/{serviceId}`**.

### What it does

- **HTTP endpoint** for Pub/Sub push: `POST /pubsub/push`
- Validates request, **decodes base64 JSON payload**
- **Idempotency** using `messageId`:
  - creates `ops_dedupe/{messageId}` with `createdAt`
  - if already present: returns **200** (no-op)
- **Stale protection** for `ops_services/{serviceId}`:
  - only overwrites if incoming timestamp \(derived from `producedAt`/`publishedAt`/`timestamp`\) is **>=** stored `lastHeartbeatAt`/`updatedAt`
- Writes Firestore read model:
  - `ops_services/{serviceId}` fields:
    - `serviceId, env, status, lastHeartbeatAt, version, region, updatedAt`
    - `source: { topic, messageId, publishedAt }`
- Emits **structured JSON logs** to stdout

### Additional topics (market data + signals)

This service can also materialize the following Pub/Sub topics:

- `market-ticks` → `market_ticks/{docId}`
- `market-bars-1m` → `market_bars_1m/{docId}`
- `trade-signals` → `trade_signals/{docId}`

**Idempotency** for these streams is implemented via deterministic doc IDs:

- `docId = eventId` if present and non-empty, else `docId = messageId`

**Stale protection** for these streams:

- writes are ignored if the incoming event time is older than the stored doc’s `eventTime`/`producedAt`/`publishedAt` (whichever is latest)
- incoming event time preference: `producedAt` → `publishedAt` → `timestamp`/`ts`/`time` → Pub/Sub `publishTime`

#### Topic inference

Pub/Sub push does not include the topic name by default. This service infers topic via:

- message attributes: `attributes.topic` (preferred)
- payload fields: `topic` / `pubsubTopic` / `sourceTopic`
- optional env mapping:
  - `SUBSCRIPTION_TOPIC_MAP='{"your-subscription-name":"market-ticks"}'`

### Expected Firestore collections + fields (server-written only)

- **`ops_services/{serviceId}`**
  - `serviceId` (string)
  - `env` (string)
  - `status` (string)
  - `lastHeartbeatAt` (timestamp, optional)
  - `version` (string)
  - `region` (string)
  - `updatedAt` (timestamp)
  - `source.topic` (string), `source.messageId` (string), `source.publishedAt` (timestamp)

- **`market_ticks/{docId}`**
  - `docId` (string)
  - `eventId` (string, optional)
  - `symbol` (string, optional)
  - `eventTime` (timestamp)
  - `producedAt` (timestamp, optional)
  - `publishedAt` (timestamp, optional)
  - `data` (map; original payload)
  - `source.topic` (string), `source.messageId` (string), `source.publishedAt` (timestamp)
  - `ingestedAt` (server timestamp)

- **`market_bars_1m/{docId}`**
  - `docId` (string)
  - `eventId` (string, optional)
  - `symbol` (string, optional)
  - `timeframe` (string; default `"1m"`)
  - `start` / `end` (timestamps, optional)
  - `eventTime` (timestamp)
  - `producedAt` / `publishedAt` (timestamps, optional)
  - `data` (map; original payload)
  - `source.*`, `ingestedAt` (as above)

- **`trade_signals/{docId}`**
  - `docId` (string)
  - `eventId` (string, optional)
  - `symbol` (string, optional)
  - `strategy` (string, optional)
  - `action` (string, optional)
  - `eventTime` (timestamp)
  - `producedAt` / `publishedAt` (timestamps, optional)
  - `data` (map; original payload)
  - `source.*`, `ingestedAt` (as above)

### Env vars

- **Required**
  - `GCP_PROJECT`
  - `ENV` (e.g. `prod` / `staging`)
  - `SYSTEM_EVENTS_TOPIC` (used for `source.topic`)
  - `DEFAULT_REGION`
- **Optional**
  - `FIRESTORE_DATABASE` (default: `(default)`)
  - `PORT` (default: `8080`)
  - `SUBSCRIPTION_TOPIC_MAP` (JSON map: subscription name → topic)
  - **Backpressure**
    - `CONSUMER_MAX_WORKERS` (default: `8`): max concurrent in-flight message processors per instance (bounds Firestore pressure).
    - `CONSUMER_QUEUE_SIZE` (default: `64`): bounded per-instance queue depth. When full, the handler returns **429** so Pub/Sub retries later.
  - **Firestore retry**
    - `FIRESTORE_RETRY_MAX_ATTEMPTS` (default: `6`)
    - `FIRESTORE_RETRY_INITIAL_BACKOFF_S` (default: `0.25`)
    - `FIRESTORE_RETRY_MAX_BACKOFF_S` (default: `6.0`)
    - `FIRESTORE_RETRY_MAX_TOTAL_S` (default: `8.0`): caps total retry time per message on transient Firestore errors.
  - **Explicit DLQ (recommended for permanent Firestore errors)**
    - `DLQ_TOPIC`: topic id (e.g. `my-consumer-dlq`) or full topic path `projects/<proj>/topics/<topic>`.
    - `DLQ_PUBLISH_DEADLINE_S` (default: `10.0`)

### Backpressure + retry policy (consumer)

- **Bounded concurrency / queueing**
  - Work is processed via a bounded in-memory queue and fixed worker pool (`CONSUMER_MAX_WORKERS`).
  - When the queue is full, the endpoint returns **429** (`backpressure_queue_full`) so Pub/Sub retries later.
- **Firestore transient retry**
  - On transient Firestore errors (`UNAVAILABLE`, `RESOURCE_EXHAUSTED`, `DEADLINE_EXCEEDED`, etc.) the consumer retries with exponential backoff + jitter.
  - Retries are capped by `FIRESTORE_RETRY_MAX_ATTEMPTS` and `FIRESTORE_RETRY_MAX_TOTAL_S`.
- **Permanent Firestore errors**
  - On `PERMISSION_DENIED` and `INVALID_ARGUMENT`, the consumer emits an **ALERT** log and (if `DLQ_TOPIC` is set) publishes the decoded message to the DLQ, then returns **200** to stop redelivery loops.

### Load test + documented safe limits

The consumer’s **safe per-instance pressure limit** is:

- **max in-flight Firestore work per instance** = `CONSUMER_MAX_WORKERS`
- **max queued (waiting) messages per instance** = `CONSUMER_QUEUE_SIZE`

To validate safe limits for your Firestore quota + doc shapes, run the load tester against a deployed instance (or local emulator):

```bash
python cloudrun_consumer/scripts/load_test_pubsub_push.py \
  --url "http://localhost:8080/pubsub/push" \
  --requests 2000 \
  --concurrency 100 \
  --topic "system.events" \
  --subscription "projects/local/subscriptions/loadtest"
```

Interpretation:

- **200s**: accepted/acked
- **429s**: backpressure working (Pub/Sub should retry later)
- **5xx**: transient failures (should be rare; indicates too much pressure, too low retry cap, or a bug)

### Run locally

From repo root:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r cloudrun_consumer/requirements.txt
cd cloudrun_consumer

export GCP_PROJECT="your-gcp-project"
export ENV="staging"
export SYSTEM_EVENTS_TOPIC="system.events"
export DEFAULT_REGION="us-central1"

python main.py
```

### Minimal test strategy (local harness)

This folder includes a small stdlib unittest suite for routing + id selection:

```bash
python -m unittest discover -s cloudrun_consumer/tests -p "test_*.py"
```

For end-to-end testing, point the service at a Firestore emulator and POST a Pub/Sub push envelope to `/pubsub/push` (with `attributes.topic` set to one of the supported topics).

### Pub/Sub push format

This service expects the standard Cloud Run Pub/Sub push envelope:

```json
{
  "message": {
    "data": "base64(JSON)",
    "messageId": "123",
    "publishTime": "2026-01-08T12:34:56.123Z",
    "attributes": {}
  },
  "subscription": "projects/.../subscriptions/..."
}
```

