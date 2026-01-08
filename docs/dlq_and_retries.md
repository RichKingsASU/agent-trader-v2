# DLQ + retries for Pub/Sub consumers writing Firestore

This doc proposes a **dead-letter queue (DLQ)** strategy, **retry vs ack/nack rules**, and **logging + alerting thresholds** for the Pub/Sub → consumer → Firestore path in this repo.

Scope:
- **Pub/Sub subscription config** (push + pull) as it affects reliability and DLQ behavior
- **Consumer error handling** in the existing consumers
- **Firestore write failures** and how they should interact with Pub/Sub retries/DLQ

Non-goals:
- No infrastructure changes are made in this change set (this is documentation only).

---

## Audit (current state in this repo)

### Subscription configuration

- **No infra-as-code for Pub/Sub subscriptions found in-repo**.
  - `infra/cloudrun/services/pubsub-event-ingestion.service.yaml` is a Cloud Run service template and explicitly says “Create a push subscription that targets `https://<service-url>/pubsub/push`”, but the subscription resource (ack deadline, retry policy, DLQ policy) is not defined in code.
- Resulting risk:
  - Subscription defaults can drift across environments.
  - DLQ behavior may be absent, which turns “poison” messages into **infinite redelivery loops** (for push: repeated HTTP calls; for pull: repeated `nack()` redelivery).

### Consumers and their current ack/retry behavior

This repo contains both **push** and **pull** consumers:

#### Push consumer: `backend/ingestion/pubsub_event_ingestion_service.py`

- Endpoint: `POST /pubsub/push`
- Behavior:
  - Persists a visibility record (`EventStore.write_event(ev)`), then conditionally applies Firestore business updates only for the ingest-heartbeat subscription id.
  - **Malformed/unexpected ingest-heartbeat payload**: returns **2xx** (“Ack malformed/unexpected payloads to avoid infinite redelivery loops.”).
  - **Firestore exception while applying heartbeat**: returns **500** so Pub/Sub retries; relies on Firestore **dedupe document keyed by Pub/Sub `messageId`** for idempotency (`ingest_pipelines_dedupe/{messageId}`).
- Risk note:
  - The “visibility” store’s Firestore summary doc uses `FieldValue.increment(1)`; if the handler later returns 500 and Pub/Sub retries, that counter can **over-count** deliveries. This is acceptable for “visibility-first” counters, but it’s not an exactly-once metric.

#### Push consumer: `cloudrun_consumer/main.py` (materializer)

- Endpoint: `POST /pubsub/push`
- Behavior:
  - Strictly validates Pub/Sub push envelope and base64 JSON payload.
  - Routes payload by shape (`schema_router.py`), currently “system events” → `ops_services/{serviceId}`.
  - **Invalid envelope/payload/unroutable/ValueError**: returns **400** (“Treat as poison for this consumer; allow DLQ routing.”).
  - **Other exceptions**: returns **500**.
  - Uses Firestore transaction-level idempotency (`ops_dedupe/{messageId}`) and stale protection.
- Key operational implication:
  - Returning **400** only “works” operationally if the subscription has a **deadLetterPolicy**. Without it, Pub/Sub push will still redeliver on non-2xx and you get a hot-loop.

#### Pull consumer helper: `backend/messaging/subscriber.py`

- Uses streaming pull (`SubscriberClient.subscribe`) and:
  - `ack()` on success
  - `nack()` on **any exception** (including parse/validation)
- Risk:
  - Poison messages will be retried forever unless the subscription has DLQ/max delivery attempts.

### Firestore write failure handling (today)

- **Ingest heartbeat** (`apply_ingest_heartbeat_to_firestore`):
  - Uses a Firestore transaction and dedupe doc (`ingest_pipelines_dedupe/{messageId}`) to be safe under retries/redelivery.
- **Generic ingestion writer** (`backend/ingestion/firebase_writer.py`):
  - Implements exponential backoff + jitter retries for common transient Firestore errors (e.g., `ResourceExhausted`, `ServiceUnavailable`, `Aborted`).
- **Materializer writer** (`cloudrun_consumer/firestore_writer.py`):
  - Uses Firestore transactions and a dedupe doc; does not add an explicit retry loop (relies on Pub/Sub redelivery + transaction retry semantics inside the client libraries).

---

## Proposed DLQ strategy (no infra changes here, but this is the target design)

### Design principles

- **At-least-once delivery is assumed**. All Firestore writes must be safe under:
  - redelivery of the same Pub/Sub message
  - out-of-order delivery
- **DLQ is per-subscription, not per-topic**, because “poison” is often consumer-specific (one consumer can’t parse what another can).
- DLQ must preserve enough context to support replay and debugging:
  - original message data + attributes
  - `messageId`, `publishTime`
  - `subscription` and (if available) `deliveryAttempt`
  - consumer error classification (transient/permanent) and error string

### Preferred: Pub/Sub native dead-letter policy

For each subscription feeding a consumer:
- Configure a **dead-letter topic**: `<subscription-id>.dlq` (or `<topic>.<consumer>.dlq`), and set:
  - `deadLetterPolicy.maxDeliveryAttempts`: **5** for high-signal “poison” streams; **10** if transient Firestore saturation is expected and you want longer tail retries.
  - `retryPolicy.minimumBackoff`: **10s**
  - `retryPolicy.maximumBackoff`: **600s** (10m)

Operational notes:
- With a DLQ policy enabled, a non-2xx push response (or `nack()` on pull) will eventually route to DLQ after `maxDeliveryAttempts`.
- Keep message retention on the DLQ topic high enough for human triage (commonly **7–14 days**).

### Fallback (when DLQ is not configured): “ack poison, retry transient”

If a subscription has no DLQ, the system must avoid infinite redelivery loops:
- **Ack (2xx / `ack()`) poison messages** after logging them as errors (and ideally persisting a minimal audit record).
- **Retry (non-2xx / `nack()`) only transient failures** that are expected to succeed later.

This fallback sacrifices automatic replay, but it prevents runaway load and cost.

---

## Retry vs nack rules

### Shared definitions

- **Ack**:
  - Push: return **2xx**
  - Pull: call `message.ack()`
- **Retry / redelivery**:
  - Push: return **non-2xx**
  - Pull: call `message.nack()` (or let ack deadline expire)

Classify failures as:
- **Permanent / poison**: retrying will not succeed without code/config/data change.
- **Transient**: likely to succeed with time/backoff (quota, timeouts, brief outages).

### Rules for Pub/Sub push → Cloud Run consumers

#### Permanent / poison → **do not retry indefinitely**

Examples:
- Not parseable base64 / invalid JSON
- Payload not matching the consumer’s schema/router
- Required fields missing (e.g., `service` for system events)

Recommended action:
- If subscription has DLQ: return **400** (or **422**) to drive delivery attempts toward DLQ.
- If subscription has no DLQ: return **2xx** and emit a **high-severity structured log** describing the poison event.

Rationale:
- Retrying poison increases load and costs and can starve good messages.

#### Transient → **retry**

Examples:
- Firestore transient errors: `ResourceExhausted` / 429, `Unavailable`, `DeadlineExceeded`, `Aborted`
- Downstream dependency outages

Recommended action:
- Return **500** (or any non-2xx) so Pub/Sub retries with backoff.
- Rely on idempotency keys (`messageId`) + stale checks to keep Firestore correct.

#### Configuration errors (permissions/identity) → **page quickly**

Examples:
- Firestore `PermissionDenied` / `Unauthenticated`
- Missing required env vars (e.g., `SYSTEM_EVENTS_TOPIC`)

Recommended action:
- Treat as **critical**:
  - return **500** (it won’t succeed until fixed)
  - alert immediately (see thresholds)
- If DLQ is enabled, you may still let messages drift to DLQ rather than drop.

### Rules for Pub/Sub streaming pull consumers

Current helper (`backend/messaging/subscriber.py`) nacks on any exception; the recommended policy is:

- **Ack** when:
  - handler succeeds
  - handler detects a **permanent** schema/validation issue (poison)
  - handler detects the message is a **duplicate** (idempotency hit) or **stale** (ordering guard)
- **Nack** when:
  - handler hits a **transient** dependency failure (timeouts, quota, brief outages)
  - handler cannot complete within ack deadline and does not support lease extension (nack is better than silent drop)

If you must keep “nack on any exception”, then DLQ with `maxDeliveryAttempts` is mandatory to prevent infinite retries.

---

## Logging requirements (what to log so DLQ + retries are operable)

All consumers should emit one structured JSON log line per message with:
- **Identity**: `service`, `env`, `sha/version`
- **Pub/Sub**:
  - `subscription` (from push envelope `subscription` when present)
  - `topic` (if known/configured; e.g., `SYSTEM_EVENTS_TOPIC`)
  - `messageId`
  - `publishTime`
  - `deliveryAttempt` (when available from Pub/Sub dead-letter enabled deliveries)
- **Routing**: `handler` / `event_type` / `schemaVersion` (when relevant)
- **Outcome**:
  - `outcome`: `applied | duplicate | stale_ignored | poison | retry`
  - `http_status` (push) or `ack_action` (pull)
- **Firestore**:
  - `write_kind` + `doc_path` (or collection/doc id)
  - `idempotency_doc` (dedupe doc path/id)
- **Errors**:
  - `error_type`, `error_code` (if available), and a bounded `error` string
  - `retryable: true|false`

Minimum logging rule:
- Any message that will be retried (push non-2xx / pull nack) should produce an **ERROR** log with enough fields to correlate retries and measure rates.

---

## Alerting thresholds (pragmatic defaults)

These are intended as **starting thresholds** for Cloud Monitoring (metrics + log-based metrics).

### DLQ alerts (highest signal)

- **DLQ message count > 0** for a critical subscription:
  - **Warning**: >0 messages for **5 minutes**
  - **Critical**: >0 messages for **15 minutes**, or **>10 messages in 10 minutes**
- **DLQ growth rate** (if measured):
  - **Critical**: DLQ incoming rate exceeds DLQ processing/replay rate for **30 minutes**

### Push consumer HTTP error-rate alerts

Use Cloud Run request metrics (or log-based metrics by `status_code`):
- **5xx rate** (transient failures, likely Firestore/downstream):
  - **Warning**: >**1%** of requests for **5 minutes**
  - **Critical**: >**5%** of requests for **5 minutes** (or any sustained 5xx for 15 minutes)
- **4xx rate** (poison / producer contract break):
  - **Warning**: >**0.1%** of requests for **10 minutes**
  - **Critical**: >**1%** of requests for **10 minutes**

Interpretation:
- A rising **4xx** rate usually indicates a producer/schema change or misrouting.
- A rising **5xx** rate usually indicates capacity/quota/dependency problems.

### Subscription backlog (work not being processed)

For each subscription:
- **Oldest unacked message age**:
  - **Warning**: >**5 minutes**
  - **Critical**: >**15 minutes**
- **Undelivered message count** (if you have a stable expected throughput):
  - **Warning**: backlog increasing for **15 minutes**
  - **Critical**: backlog increasing for **30 minutes**

### Firestore failure/saturation indicators

Use log-based metrics (recommended) and/or Firestore service metrics:
- **Firestore transient error logs** (429/ResourceExhausted/Unavailable/DeadlineExceeded):
  - **Warning**: ≥**5/min** for **10 minutes**
  - **Critical**: ≥**20/min** for **10 minutes**
- **Firestore PermissionDenied/Unauthenticated**:
  - **Critical** immediately (these are rarely self-healing)

---

## Recommended subscription defaults (to standardize across environments)

Even though subscriptions are not defined in this repo today, standardize them as follows when creating them:

- **Push subscriptions (Cloud Run)**
  - Push endpoint: `https://<service-url>/pubsub/push`
  - Retry policy: min backoff **10s**, max backoff **600s**
  - Dead-letter policy: enabled, `maxDeliveryAttempts` **5–10**
  - Authentication (recommended hardening): Pub/Sub push with OIDC token + Cloud Run IAM (documented here to avoid unauthenticated push).

- **Pull subscriptions (streaming pull)**
  - Ack deadline: set to **max expected processing time** (start with **60s** if unsure)
  - Dead-letter policy: enabled, `maxDeliveryAttempts` **5–10**
  - If processing can exceed ack deadline: implement lease extension or increase ack deadline; do not rely on repeated nack loops.

---

## Immediate follow-ups (documentation-only; no code/infra changes in this PR)

- Document the actual subscription resource parameters (per environment) somewhere versioned (IaC or a runbook).
- Ensure every subscription that can produce **400/`nack()`** on poison has a DLQ policy.
- Align consumer behavior with this doc:
  - If DLQ is absent, avoid non-2xx on permanent schema errors (otherwise it will redeliver forever).

