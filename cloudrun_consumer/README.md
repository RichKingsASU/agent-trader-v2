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

