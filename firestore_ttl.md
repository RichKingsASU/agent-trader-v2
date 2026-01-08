# Firestore Operational Dashboard — TTL Policies

This document defines **recommended TTL (time-to-live) policies** for ephemeral operational data produced by Pub/Sub read models.

## Principles

- **Primary read-model docs do not expire** by TTL (they represent current state).
- TTL is used for **bounded drilldown** data stored in subcollections/collection-groups.
- TTL fields must be Firestore `timestamp` fields (not strings), populated by the server writer.

---

## TTL 1 — `recent_errors` collection group (recommended)

### Scope

If you add `recent_errors` subcollections under any of these, TTL should apply:

- `ops_services/{serviceId}/recent_errors/{errorId}`
- `ops_strategies/{strategyId}/recent_errors/{errorId}`
- `ingest_pipelines/{pipelineId}/recent_errors/{errorId}`

Firestore TTL is configured on the **collection group** name `recent_errors`, so it covers all of the above.

### TTL field

- **Field**: `expiresAt` (timestamp)

### Retention recommendation

- **7 days** retention for operational drilldown (adjust per compliance needs).

### Writer behavior

- On write, set:
  - `seenAt = <event timestamp or now>`
  - `expiresAt = seenAt + 7 days`

### How to enable (per project)

Run for each Firebase project (e.g. `agenttrader-dev`, `agenttrader-staging`, `agenttrader-prod`):

```bash
gcloud config set project agenttrader-dev
gcloud firestore fields ttl update expiresAt --collection-group=recent_errors --enable-ttl
```

Notes:

- TTL deletion is **asynchronous**; documents may persist beyond `expiresAt` for some time.
- TTL deletes are performed by Firestore; treat TTL data as **best-effort retention**.

---

## TTL 2 — `sampled_dlq` collection group (optional)

### Scope

If you store sampled dead-letter messages for debugging:

- `ingest_pipelines/{pipelineId}/sampled_dlq/{messageId}`

Firestore TTL can be configured on the **collection group** `sampled_dlq`.

### TTL field

- **Field**: `expiresAt` (timestamp)

### Retention recommendation

- **72 hours (3 days)** retention (keeps costs low and reduces sensitive data exposure).

### Writer behavior

- On write, set:
  - `receivedAt = now`
  - `expiresAt = receivedAt + 72 hours`
- Ensure payload is **sanitized** (no secrets/PII) before writing to Firestore.

### How to enable (per project)

```bash
gcloud config set project agenttrader-dev
gcloud firestore fields ttl update expiresAt --collection-group=sampled_dlq --enable-ttl
```

---

## Recommended TTL “do not”

- Do **not** TTL-delete `ops_services`, `ops_strategies`, `ingest_pipelines`, or `ops_alerts` documents; those should represent current state.
- Do **not** rely on TTL for correctness (it’s a cost/retention control, not a transactional guarantee).

