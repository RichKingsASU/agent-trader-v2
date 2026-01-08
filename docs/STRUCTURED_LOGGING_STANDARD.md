## Structured Logging Standard (JSON)

This repo standardizes **one-JSON-object-per-line** logs for deployable services (notably:
`cloudrun_ingestor/` and `cloudrun_consumer/`).

### Required stable keys

All services must emit (where applicable) the following **stable** keys so logs are queryable and
usable for log-based metrics:

- **`service`**: logical service name (Cloud Run `K_SERVICE` / explicit override)
- **`env`**: environment name (e.g. `prod`, `staging`)
- **`version`**: deploy version identifier (e.g. `K_REVISION` / `IMAGE_TAG`)
- **`correlation_id`**: request/message correlation ID (propagated when present; otherwise generated)
- **`event_id`**: business/event identifier (for Pub/Sub: prefer payload `eventId`, else `messageId`)
- **`topic`**: Pub/Sub topic or logical stream name
- **`outcome`**: `success` / `failure` / `noop` / `duplicate` / `degraded` (use a small fixed vocabulary)
- **`latency_ms`**: end-to-end time for the operation being logged (integer milliseconds)

### Canonical event field

Use **`event_type`** as the canonical event discriminator (examples: `pubsub.rejected`, `materialize.ok`).

### Examples

Success:

```json
{"timestamp":"2026-01-08T12:34:56.123456+00:00","severity":"INFO","service":"cloudrun-pubsub-firestore-materializer","env":"prod","version":"rev-00012-abc","request_id":"...","correlation_id":"0f2b2b4b-9b10-4c4f-9e4d-3b8c8d3c0f6d","event_type":"materialize.ok","event_id":"evt_01H...","topic":"market-ticks","outcome":"success","latency_ms":42,"subscription":"projects/.../subscriptions/...","deliveryAttempt":1}
```

Failure:

```json
{"timestamp":"2026-01-08T12:34:56.123456+00:00","severity":"ERROR","service":"cloudrun-pubsub-firestore-materializer","env":"prod","version":"rev-00012-abc","request_id":"...","correlation_id":"0f2b2b4b-9b10-4c4f-9e4d-3b8c8d3c0f6d","event_type":"pubsub.rejected","event_id":"1234567890","topic":"market-ticks","outcome":"failure","latency_ms":3,"reason":"invalid_payload_json"}
```

### Cloud Logging queries

#### Find all logs for a single event

Filter:

- `jsonPayload.event_id="YOUR_EVENT_ID"`

#### Find all logs for a correlated workflow

Filter:

- `jsonPayload.correlation_id="YOUR_CORRELATION_ID"`

#### Narrow to Cloud Run + service

Filter:

- `resource.type="cloud_run_revision"`
- `jsonPayload.service="cloudrun-pubsub-firestore-materializer"`
- `jsonPayload.correlation_id="..."`

### Log-based metric filters (examples)

#### Count processing failures

Filter:

- `resource.type="cloud_run_revision"`
- `jsonPayload.service="cloudrun-pubsub-firestore-materializer"`
- `jsonPayload.outcome="failure"`

#### Count successful materializations per topic

Filter:

- `resource.type="cloud_run_revision"`
- `jsonPayload.event_type="materialize.ok"`
- `jsonPayload.outcome="success"`
- `jsonPayload.topic="market-ticks"`

