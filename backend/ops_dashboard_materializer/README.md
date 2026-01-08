## Ops Dashboard Materializer (Option A)

**Architecture lock**: Pub/Sub is canonical source of truth. This Cloud Run service **materializes Firestore read models** for the Ops Dashboard. The frontend is **read-only** and must never write operational state.

### Data flow

Pub/Sub (canonical) → **Cloud Run push subscription** → `backend.ops_dashboard_materializer.service` → Firestore (derived projections, latest-only)

### Firestore read models (authoritative for UI)

This service writes **only** these collections (latest state only, no raw events, no history):

- `ops_services/{serviceId}`
  - `status`, `lastHeartbeatAt`, `version`, `region`, `instanceCount`
  - `source`: `{ topic, subscription, messageId, publishedAt }`
- `ops_strategies/{strategyId}`
  - `mode`, `status`, `lastDecisionAt`, `lastHeartbeatAt`
- `ingest_pipelines/{pipelineId}`
  - `status`, `lagSeconds`, `throughputPerMin`, `errorRatePerMin`
  - `lastSuccessAt`, `lastErrorAt`, `lastEventAt`
- `ops_alerts/{alertId}`
  - `severity`, `state`, `entityRef`, `firstSeenAt`, `lastSeenAt`
  - `alertId` is **deterministic** (idempotent)

### Processing rules (mandatory)

- **At-least-once safe**: Pub/Sub duplicates must not corrupt state.
  - State docs are updated idempotently by stable doc IDs.
  - Alerts use a deterministic `alertId` (prefers `dedupeKey/fingerprint/alertId`, else a compact hash).
- **Ordering-agnostic**: stale events are rejected (timestamp compare).
  - `ops_services`: compares incoming Pub/Sub `publishTime` vs stored `source.publishedAt`
  - `ops_strategies`: compares incoming max(`lastDecisionAt`,`lastHeartbeatAt`) vs existing
  - `ingest_pipelines`: compares incoming `lastEventAt` vs existing
  - `ops_alerts`: compares incoming `publishTime` vs existing `lastSeenAt`
- **Schema-version aware**: reads `schemaVersion` (attributes or payload), defaults to `1`.
  - Basic key normalization is applied (`snake_case` → canonical camelCase) to translate older payloads forward.
- **Retries + DLQ compatible**:
  - Non-2xx responses cause Pub/Sub retries; if DLQ is configured on the subscription, poison messages can route there.
- **Structured logs only**: uses repo’s JSON logging (no `print` statements).

### Topic → collection mapping

Pub/Sub push payloads include the **subscription** but not the **topic**. For `ops_services`, Firestore requires `source.topic`, so this service uses an explicit routing table that includes the topic name.

Routing is configured via `DASHBOARD_MATERIALIZER_ROUTES_JSON`:

```json
[
  {
    "subscription": "projects/PROJECT/subscriptions/ops-services-sub",
    "kind": "ops_services",
    "topic": "ops.status"
  },
  {
    "subscription": "projects/PROJECT/subscriptions/ops-strategies-sub",
    "kind": "ops_strategies"
  },
  {
    "subscription": "projects/PROJECT/subscriptions/ingest-pipelines-sub",
    "kind": "ingest_pipelines"
  },
  {
    "subscription": "projects/PROJECT/subscriptions/ops-alerts-sub",
    "kind": "ops_alerts"
  }
]
```

`kind` values are fixed:
- `ops_services`
- `ops_strategies`
- `ingest_pipelines`
- `ops_alerts`

### Running (local)

This is a standard FastAPI app:

- Module: `backend.ops_dashboard_materializer.service:app`
- Endpoint: `POST /pubsub/push`

Required env:
- `FIREBASE_PROJECT_ID` (or `GOOGLE_CLOUD_PROJECT`)
- ADC credentials must be available (Firebase Admin SDK requirement)
- `DASHBOARD_MATERIALIZER_ROUTES_JSON` (required; unrouted subscriptions return non-2xx to enable DLQ)

### Pub/Sub push format expected

Standard Cloud Run push subscription envelope:

```json
{
  "message": {
    "data": "base64...",
    "attributes": { "schemaVersion": "1" },
    "messageId": "123",
    "publishTime": "2026-01-08T12:34:56.123Z"
  },
  "subscription": "projects/.../subscriptions/..."
}
```

