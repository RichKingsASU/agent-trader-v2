## On-call Runbook: Ingestor / Consumer / Pub/Sub Backlog

This runbook is optimized for **fast, safe incident response** for the ingestion → Pub/Sub → consumer → Firestore paths in this repo.

### Scope (what this runbook covers)

- **Ingestor failures**: producers that publish to Pub/Sub (notably `cloudrun_ingestor`, and any other service using `backend/messaging/publisher.py`).
- **Consumer failures**: Pub/Sub push consumers (notably `cloudrun_consumer` and `backend/ingestion/pubsub_event_ingestion_service.py` deployed as `pubsub-event-ingestion`).
- **Pub/Sub backlog**: subscriptions building undelivered / old messages, and DLQ growth.

### Safety guardrails (non-negotiable)

- **Do not enable trade execution** as part of incident response. Keep execution workloads **OFF / halted** (see `docs/ops/agent_mesh.md` and `docs/KILL_SWITCH.md`).
- **Prefer stopping the blast radius** (pause/disable publishing) over “letting it burn” (hot loops, infinite retries).
- **Assume at-least-once delivery**. Consumers must be safe under redelivery and out-of-order messages (see `docs/dlq_and_retries.md`).

### What to have handy (fill in per environment)

- **Project/region**: `<PROJECT_ID>`, `<REGION>`
- **Ingestor service name(s)**: e.g. `cloudrun-ingestor` (Cloud Run service running `cloudrun_ingestor/main.py`)
- **Consumer service name(s)**:
  - `cloudrun_consumer` (Pub/Sub push → Firestore materializer, `POST /pubsub/push`)
  - `pubsub-event-ingestion` (FastAPI push consumer, `POST /pubsub/push`)
- **Critical topics** (commonly):
  - `SYSTEM_EVENTS_TOPIC`
  - `MARKET_TICKS_TOPIC`
  - `MARKET_BARS_1M_TOPIC`
  - `TRADE_SIGNALS_TOPIC`
- **Critical subscriptions** (commonly):
  - `<SUBSCRIPTION_ID>` (main)
  - `<DLQ_SUBSCRIPTION_ID>` (dead-letter subscription, if configured)

---

## Quick triage (2–5 minutes)

Use this to decide which checklist to run first.

- **If producer logs show publish failures** (`jsonPayload.event_type="pubsub_publish_failure"`): run **Ingestor failure checklist**.
- **If Pub/Sub backlog/oldest age is rising** but you don’t yet know why: run **Pub/Sub backlog checklist** (it points you to producer vs consumer).
- **If Cloud Run consumer has elevated 4xx/5xx on `/pubsub/push`**: run **Consumer failure checklist**.

Helpful repository references:

- **Alert patterns and suggested thresholds**: `docs/alerts_v1.md`
- **DLQ / retry semantics and “poison vs transient” rules**: `docs/dlq_and_retries.md`
- **Live quotes heartbeat contract (if UI is involved)**: `docs/LIVE_QUOTES_FLOW.md`

---

## 1) Ingestor failure checklist (producer → Pub/Sub)

Applies to `cloudrun_ingestor` and any publisher using `backend/messaging/publisher.py`.

### A. Confirm and classify the failure

- [ ] **Find a failing log entry** in Cloud Logging for the ingestor service revision.
  - Look for: `jsonPayload.event_type="pubsub_publish_failure"`
  - Capture: `jsonPayload.topic`, `jsonPayload.error_code`, `jsonPayload.error_type`, `jsonPayload.attempt`, `jsonPayload.max_attempts`, `jsonPayload.trace_id`
- [ ] **Classify by `error_code`** (guidance from `docs/alerts_v1.md`):
  - **PERMISSION_DENIED / UNAUTHENTICATED**: IAM / identity / ADC issue (page/urgent).
  - **NOT_FOUND**: wrong topic name/project or topic deleted.
  - **DEADLINE_EXCEEDED / UNAVAILABLE / RESOURCE_EXHAUSTED**: transient platform/quota/network pressure.
  - **INVALID_ARGUMENT**: topic path/attributes/payload issue (usually config or code regression).

### B. Verify basic ingestor health (Cloud Run + config)

- [ ] **Confirm the service is running** (request count > 0, no crash loops, no OOMKilled).
- [ ] **Check required env vars exist** for `cloudrun_ingestor` (from `cloudrun_ingestor/main.py`):
  - `GCP_PROJECT_ID`
  - `SYSTEM_EVENTS_TOPIC`, `MARKET_TICKS_TOPIC`, `MARKET_BARS_1M_TOPIC`, `TRADE_SIGNALS_TOPIC`
  - `INGEST_FLAG_SECRET_ID`
- [ ] **Check the “ingest enabled” feature flag behavior**:
  - If logs show “Ingestion is disabled via feature flag”, publishing is intentionally paused. Confirm expected state and the secret value.

### C. Fix by failure mode

#### IAM / identity (`PERMISSION_DENIED`, `UNAUTHENTICATED`)

- [ ] Identify the **Cloud Run runtime service account** used by the ingestor.
- [ ] Ensure it has **Pub/Sub publish permissions** (typically `roles/pubsub.publisher`) on the **topic or project**.
- [ ] Ensure it can read `INGEST_FLAG_SECRET_ID` if the flag is in Secret Manager (`roles/secretmanager.secretAccessor`).
- [ ] Mitigation: after IAM fix, **restart/redeploy** the Cloud Run service to refresh tokens (if necessary).

#### Topic missing / wrong project (`NOT_FOUND`)

- [ ] Validate topic existence in the intended `<PROJECT_ID>`.
- [ ] Validate the ingestor is pointed at the right project/topic names (env vars).
- [ ] Mitigation: **create/restore the topic** or correct config and redeploy.

#### Transient publish timeouts / quota (`DEADLINE_EXCEEDED`, `UNAVAILABLE`, `RESOURCE_EXHAUSTED`)

- [ ] Check whether failures correlate with a deploy, traffic spike, or GCP incident.
- [ ] Check whether multiple topics/services are failing (project-wide quota/incident) vs only one revision (bad deploy).
- [ ] Mitigation options (safe, reversible):
  - Reduce publishing volume (increase intervals / reduce batch size upstream).
  - Increase Cloud Run CPU/memory for the ingestor (avoid CPU starvation during publish).
  - Temporarily **disable ingest via feature flag** to stop repeated failures while you recover downstream.

### D. Verify recovery

- [ ] Logs show `jsonPayload.event_type="pubsub_publish_success"` again.
- [ ] `pubsub_publish_failure` rate returns to baseline.
- [ ] Downstream subscriptions stop accumulating backlog (see Pub/Sub backlog checklist).

---

## 2) Consumer failure checklist (Pub/Sub push → Firestore)

Applies to push consumers:

- `cloudrun_consumer` (`POST /pubsub/push`, routes and materializes to Firestore; see `cloudrun_consumer/README.md`)
- `pubsub-event-ingestion` (`backend/ingestion/pubsub_event_ingestion_service.py`, also `POST /pubsub/push`)

### A. Identify which consumer/subscription is failing

- [ ] Determine impacted **subscription id** (from the Pub/Sub push envelope `subscription`, or from Monitoring).
- [ ] Determine impacted **consumer service**:
  - Elevated Cloud Run **request 4xx/5xx** on the consumer service.
  - Consumer logs correlated with the timeframe.

### B. Split by HTTP failure class (critical branching)

#### 4xx from consumer: “poison” / contract mismatch / push auth issue

- [ ] **If 401/403**:
  - Likely Pub/Sub push authentication / Cloud Run IAM mismatch (OIDC token/Invoker).
  - Mitigation: fix push auth/IAM; consider temporarily routing to a “catch-all” endpoint only if you can preserve security.
- [ ] **If 400/422**:
  - `cloudrun_consumer` intentionally returns **400** for invalid envelope/payload/unroutable (see `docs/dlq_and_retries.md`).
  - Key risk: **without a DLQ policy**, non-2xx push responses can cause **infinite redelivery hot loops**.
  - Actions:
    - [ ] Confirm the subscription has a **deadLetterPolicy** configured.
    - [ ] Inspect a sample failing payload (from logs/DLQ) and identify the producer change that broke schema/routing.
    - [ ] Mitigate by rolling back/fixing the **producer** or updating the consumer router/handler.

#### 5xx from consumer: transient dependency / quota / platform

- [ ] Inspect consumer logs for Firestore error codes/types:
  - **PERMISSION_DENIED / UNAUTHENTICATED**: IAM/identity problem (urgent).
  - **RESOURCE_EXHAUSTED (429)**: Firestore quota / hot document / too many writes.
  - **UNAVAILABLE / DEADLINE_EXCEEDED**: transient Firestore/network issues.
  - **ABORTED**: transaction contention (often hot-spotting).
- [ ] Confirm Firestore API metrics show elevated non-2xx writes (see `docs/alerts_v1.md`).
- [ ] Mitigation options:
  - IAM fix for Firestore roles (Firestore roles are under Datastore, e.g. `roles/datastore.user`).
  - Reduce write pressure (slow publishers, coalesce heartbeats/events).
  - Increase consumer capacity (Cloud Run resources / concurrency / max instances) to drain backlog once Firestore is healthy.

### C. Consumer-specific checks

#### `cloudrun_consumer` (materializer)

- [ ] Confirm it is receiving valid Pub/Sub push envelopes and has required env vars (see `cloudrun_consumer/README.md`):
  - `GCP_PROJECT`, `ENV`, `SYSTEM_EVENTS_TOPIC`, `DEFAULT_REGION` (and optional `SUBSCRIPTION_TOPIC_MAP`)
- [ ] Confirm idempotency writes succeed:
  - `ops_dedupe/{messageId}` is created transactionally; duplicates should become no-ops.
- [ ] If Firestore contention is suspected:
  - `ops_services/{serviceId}` is a **hot doc** under frequent heartbeats (see `docs/consumer_safety_check.md`).

#### `pubsub-event-ingestion` (visibility + ingest heartbeat apply)

- [ ] Confirm the subscription id matches `INGEST_HEARTBEAT_SUBSCRIPTION_ID` (default `ingest-heartbeat`).
- [ ] If heartbeat apply is failing (500s):
  - It is designed to **return 500 so Pub/Sub retries**, relying on dedupe (`ingest_pipelines_dedupe/{messageId}`).
- [ ] Confirm service health endpoints if debugging platform issues:
  - `GET /healthz`, `GET /readyz`, `GET /livez`

### D. Verify recovery

- [ ] Consumer `/pubsub/push` returns steady **2xx**.
- [ ] Pub/Sub subscription **oldest unacked age** trends down.
- [ ] DLQ stops growing (if configured).
- [ ] Firestore error rate returns to baseline; transactions stop aborting at high rates.

---

## 3) Pub/Sub backlog checklist (subscriptions building lag)

Use this when:

- `num_undelivered_messages` is rising, or
- `oldest_unacked_message_age` is rising, or
- DLQ is non-zero / growing.

### A. Confirm backlog scope and severity

- [ ] Identify the affected **subscription id(s)**.
- [ ] Record:
  - `pubsub.googleapis.com/subscription/num_undelivered_messages`
  - `pubsub.googleapis.com/subscription/oldest_unacked_message_age`
  - If DLQ exists: DLQ subscription backlog and oldest age
- [ ] Determine whether the backlog is:
  - **New and sharply rising** (likely outage/regression)
  - **Slow creep** (capacity/throughput mismatch)
  - **Only certain event types** (producer contract issue or hot partition/consumer routing)

### B. Decide: is it producer-side or consumer-side?

#### Producer-side indicators (upstream isn’t publishing correctly)

- [ ] Pub/Sub backlog is flat/low, but downstream state is stale (e.g., no new events visible).
- [ ] Ingestor logs show `pubsub_publish_failure` spikes or no `pubsub_publish_success`.
- [ ] Action: run **Ingestor failure checklist**.

#### Consumer-side indicators (messages exist but aren’t being acked/processed)

- [ ] Backlog and/or oldest age is rising.
- [ ] Consumer Cloud Run request count is:
  - **Zero/near-zero**: subscription push endpoint misconfigured, service URL changed, IAM invoker/auth failure.
  - **Non-zero with high 4xx/5xx**: consumer is rejecting or failing (run **Consumer failure checklist**).
  - **Non-zero with low errors but still lagging**: consumer is too slow / underprovisioned.

### C. Remediation actions (safe ordering)

- [ ] **Stop the bleeding first**:
  - If backlog growth is driven by a broken producer deploy, roll back/fix the producer.
  - If messages are poison and flooding, **pause publishing** (feature flag) until schema is fixed.
- [ ] **Fix the processing bottleneck**:
  - Firestore IAM/quota/availability issues.
  - Consumer resource limits (CPU/memory) and scaling settings.
  - Hot document contention (transaction aborts).
- [ ] **Then drain**:
  - Scale consumer (temporarily increase max instances / concurrency) once it is healthy.
  - Monitor oldest age trending down; avoid oscillation (scale back once stable).

### D. DLQ-specific steps (when DLQ > 0)

- [ ] Confirm the subscription has dead-letter policy enabled (see `docs/dlq_and_retries.md`).
- [ ] Inspect a sample DLQ payload to classify:
  - **Poison** (schema mismatch, missing fields, invalid base64/JSON): fix producer/consumer contract, then replay.
  - **Transient** (Firestore unavailable/quota): fix dependency, then replay.
- [ ] Replay only when:
  - Consumer is healthy and idempotency is confirmed.
  - You have a bounded replay plan (rate-limited; avoid re-creating the outage).

### E. Verify recovery

- [ ] Main subscription backlog stabilizes then decreases; oldest age returns to baseline.
- [ ] DLQ backlog decreases to 0 (or to an expected steady-state).
- [ ] No sustained consumer 4xx/5xx; no sustained ingestor publish failures.

---

## Appendix: “known-good” signals and log filters (copy/paste friendly)

### Ingestor (publisher) logs

- Publish failures: `jsonPayload.event_type="pubsub_publish_failure"`
- Publish successes: `jsonPayload.event_type="pubsub_publish_success"`

### Push consumer request correlation

- Pub/Sub push path: `httpRequest.requestUrl:"/pubsub/push"`

### Firestore write errors (consumer-side)

- See the filters and error taxonomy in `docs/alerts_v1.md` (Alert 4 and Alert 5).

