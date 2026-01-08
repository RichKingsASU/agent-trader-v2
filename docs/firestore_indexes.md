# Firestore indexes + hot queries + TTL (ops read models)

Scope: **read models** written server-side and read by the ops UI:

- `ops_services`
- `ingest_pipelines`
- `ops_alerts`

This document focuses on **Firestore query performance** and **cost control**:

- **Composite indexes** to support common filtered/sorted dashboard queries.
- **Hot queries** (high QPS / high fan-out) to watch and optimize first.
- **TTL policies** for bounded “drilldown” data and dedupe artifacts.

---

## Important: field naming consistency (avoid double-indexing)

This repo currently has mixed field conventions:

- Canonical materialized read model fields are **camelCase** (e.g. `updatedAt`, `lastSeenAt`, `lagSeconds`) as described in `firestore_schema.md` and written by `backend/ops_dashboard_materializer`.
- Some UI queries and legacy writers use **snake_case** (e.g. `updated_at`, `created_at`, `lag_seconds`).

**Recommendation**: pick **one canonical set** for each collection (prefer the schema’s camelCase) and migrate the UI queries to match. Otherwise you end up:

- maintaining **duplicate indexes** (camelCase + snake_case),
- paying **extra write amplification** for indexes you don’t use,
- and risking query failures when `orderBy()` targets a missing field.

The composite index proposals below assume **camelCase**. If you must keep snake_case fields, mirror the same indexes with snake_case field names.

---

## Hot queries (what will dominate reads)

These are “hot” because they are **realtime listeners** (fan-out per connected client) and/or have **tight polling/refresh loops** during incidents.

### `ops_services` hot queries

- **Overview listener**: `orderBy(updated_at desc) limit(50)` (current UI)
  - Expected evolution: add server-side filters like `where(status == "degraded") orderBy(updatedAt desc)`.
- **Service detail**: `doc("ops_services/{serviceId}")` (cheap, not hot unless very high user count)

Risk factors:

- Any “all services” listener without a `limit()` (currently bounded).
- Adding `where(env == "prod")` + `orderBy(updatedAt)` will require composite indexes.

### `ingest_pipelines` hot queries

- **Overview listener**: `orderBy(updated_at desc) limit(50)`
- **Ingest health listener**: `orderBy(updated_at desc) limit(200)`
  - This is a likely top read-driver because it subscribes to a larger slice.

Expected evolution:

- “Most lagged” view: `where(status == "degraded") orderBy(lagSeconds desc) limit(N)` (composite required).

### `ops_alerts` hot queries

- **Overview listener**: `orderBy(created_at desc) limit(50)` then client-side filter for “open”
  - This wastes reads if closed/resolved alerts dominate recent history.

Recommended evolution (more efficient):

- `where(state in ["open","acked"]) orderBy(lastSeenAt desc) limit(50)` (composite required).
- Triage: `where(state == "open") where(severity in ["error","critical"]) orderBy(lastSeenAt desc)` (composite required).

---

## Proposed composite indexes (minimal set)

Firestore automatically creates **single-field indexes**. Composite indexes are only needed when you combine:

- `where(...)` on one field + `orderBy(...)` on a different field
- multiple `where(...)` clauses (esp. equality + `in`/range) + sorting

Below is a minimal composite index set that covers the common dashboard/triage flows while keeping index write-cost under control.

### `ops_services`

1) **Services by status, most recently updated**

- **Query**: `where("status","==", <status>) orderBy("updatedAt","desc") limit(N)`
- **Index**: `status ASC, updatedAt DESC`

2) **Services by env+status, most recently updated** (only if you run multi-env in one project)

- **Query**: `where("env","==","prod") where("status","in",[...]) orderBy("updatedAt","desc")`
- **Index**: `env ASC, status ASC, updatedAt DESC`

3) **Services by stale heartbeat (range query)** (optional but common)

- **Query**: `where("lastHeartbeatAt","<", cutoff) orderBy("lastHeartbeatAt","asc") limit(N)`
- **Index**: often satisfied by single-field index on `lastHeartbeatAt`, but if you also filter by `env`:
  - `where("env","==","prod") where("lastHeartbeatAt","<", cutoff) orderBy("lastHeartbeatAt","asc")`
  - **Index**: `env ASC, lastHeartbeatAt ASC`

### `ingest_pipelines`

4) **Most lagged degraded pipelines**

- **Query**: `where("status","==","degraded") orderBy("lagSeconds","desc") limit(N)`
- **Index**: `status ASC, lagSeconds DESC`

5) **Pipelines by env + lag** (optional; multi-env-in-one-project)

- **Query**: `where("env","==","prod") where("status","in",[...]) orderBy("lagSeconds","desc") limit(N)`
- **Index**: `env ASC, status ASC, lagSeconds DESC`

6) **Recently changed pipelines by status**

- **Query**: `where("status","==", <status>) orderBy("updatedAt","desc") limit(N)`
- **Index**: `status ASC, updatedAt DESC`

### `ops_alerts`

7) **Active alerts feed**

- **Query**: `where("state","in",["open","acked"]) orderBy("lastSeenAt","desc") limit(N)`
- **Index**: `state ASC, lastSeenAt DESC`

8) **Triage feed (open + high severity)**

- **Query**: `where("state","==","open") where("severity","in",["error","critical"]) orderBy("lastSeenAt","desc")`
- **Index**: `state ASC, severity ASC, lastSeenAt DESC`

9) **Active alerts by source** (optional; useful during incidents)

- **Query**: `where("state","in",["open","acked"]) where("source","==","ingest") orderBy("lastSeenAt","desc")`
- **Index**: `source ASC, state ASC, lastSeenAt DESC`

10) **Active alerts by entity** (optional; “show me alerts for this pipeline/service”)

- **Query**: `where("state","in",["open","acked"]) where("entityRef","==", <ref>) orderBy("lastSeenAt","desc")`
- **Index**: `entityRef ASC, state ASC, lastSeenAt DESC`

---

## Suggested `firestore.indexes.json` (copy/paste template)

This repo doesn’t currently include `firestore.indexes.json`. If you want these managed via Firebase CLI, create one at repo root and deploy via `firebase deploy --only firestore:indexes`.

> If you keep snake_case fields, duplicate the relevant index entries with snake_case names.

```json
{
  "indexes": [
    {
      "collectionGroup": "ops_services",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "status", "order": "ASCENDING" },
        { "fieldPath": "updatedAt", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "ops_services",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "env", "order": "ASCENDING" },
        { "fieldPath": "status", "order": "ASCENDING" },
        { "fieldPath": "updatedAt", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "ops_services",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "env", "order": "ASCENDING" },
        { "fieldPath": "lastHeartbeatAt", "order": "ASCENDING" }
      ]
    },

    {
      "collectionGroup": "ingest_pipelines",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "status", "order": "ASCENDING" },
        { "fieldPath": "lagSeconds", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "ingest_pipelines",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "env", "order": "ASCENDING" },
        { "fieldPath": "status", "order": "ASCENDING" },
        { "fieldPath": "lagSeconds", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "ingest_pipelines",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "status", "order": "ASCENDING" },
        { "fieldPath": "updatedAt", "order": "DESCENDING" }
      ]
    },

    {
      "collectionGroup": "ops_alerts",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "state", "order": "ASCENDING" },
        { "fieldPath": "lastSeenAt", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "ops_alerts",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "state", "order": "ASCENDING" },
        { "fieldPath": "severity", "order": "ASCENDING" },
        { "fieldPath": "lastSeenAt", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "ops_alerts",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "source", "order": "ASCENDING" },
        { "fieldPath": "state", "order": "ASCENDING" },
        { "fieldPath": "lastSeenAt", "order": "DESCENDING" }
      ]
    },
    {
      "collectionGroup": "ops_alerts",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "entityRef", "order": "ASCENDING" },
        { "fieldPath": "state", "order": "ASCENDING" },
        { "fieldPath": "lastSeenAt", "order": "DESCENDING" }
      ]
    }
  ],
  "fieldOverrides": []
}
```

Notes:

- The `order` for equality-filtered fields is still specified in composite indexes (Firestore requires it).
- Only add the `env`/`source`/`entityRef` variants if you actually run those queries; each extra index increases write cost.

---

## TTL recommendations

### What should **not** be TTL-deleted

Do **not** TTL-delete these primary read-model documents:

- `ops_services/{serviceId}`
- `ingest_pipelines/{pipelineId}`
- `ops_alerts/{alertId}`

These collections represent “current state”; TTL would cause the UI to show disappearing entities.

### What **should** be TTL-managed (bounded drilldown)

These are already described in `firestore_ttl.md`; the recommendation here is to treat them as required for performance/cost hygiene:

- **`recent_errors` collection group** (recommended)
  - Paths like `ops_services/{id}/recent_errors/{errorId}` and `ingest_pipelines/{id}/recent_errors/{errorId}`
  - **TTL field**: `expiresAt` (timestamp)
  - **Retention**: **7 days**

- **`sampled_dlq` collection group** (optional)
  - Path: `ingest_pipelines/{id}/sampled_dlq/{messageId}`
  - **TTL field**: `expiresAt` (timestamp)
  - **Retention**: **72 hours**

### Additional TTL targets (recommended in this repo)

These collections can grow unbounded and are not user-facing “current state”:

- **`ops_dedupe/{messageId}`** (used by `cloudrun_consumer` for idempotency)
  - **Retention**: **7–30 days**
  - Rationale: you only need dedupe over the maximum retry/duplication window you care about; keeping forever bloats storage and indexes.

- **`ingest_pipelines_dedupe/{pubsub_message_id}`** (used by `backend/ingestion/ingest_heartbeat_handler.py`)
  - **Retention**: **7–30 days**

Implementation pattern:

- Add `expiresAt` on these dedupe docs and enable TTL on their collection groups (`ops_dedupe`, `ingest_pipelines_dedupe`).

---

## Practical next steps (lowest effort / highest impact)

- **Normalize fields**: update the ops UI to `orderBy("updatedAt")` / `orderBy("lastSeenAt")` and remove reliance on `updated_at`/`created_at` once data is migrated.
- **Move “open alerts” filtering server-side**: switch to `where(state in ["open","acked"]) orderBy(lastSeenAt desc)` to reduce wasted reads.
- **Add only the minimal composite indexes** above, then monitor index build completion and query performance before adding more.

