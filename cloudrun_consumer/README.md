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

### Env vars

- **Required**
  - `GCP_PROJECT`
  - `ENV` (e.g. `prod` / `staging`)
  - `SYSTEM_EVENTS_TOPIC` (used for `source.topic`)
  - `DEFAULT_REGION`
- **Optional**
  - `FIRESTORE_DATABASE` (default: `(default)`)
  - `PORT` (default: `8080`)

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

