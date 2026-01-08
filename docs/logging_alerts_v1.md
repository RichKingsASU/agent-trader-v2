# Logging & Alerting v1 (Cloud Run ingestor + consumer)

This document proposes **log-based metrics** and **alerts** for two services:
- **cloudrun_ingestor (expected)**: services that **publish to Pub/Sub** using `backend/messaging/publisher.py` (logs `pubsub_publish_success` / `pubsub_publish_failure`).
- **cloudrun_consumer (current)**: `cloudrun_consumer/` (**Pub/Sub push → Firestore materializer**) (logs `materialize.*` and `pubsub.*` decode/validation errors).

Scope focus (per task): **publish failures**, **auth errors**, **consumer write failures**, **DLQ growth**, **silent stalls**.  
No infra changes are proposed here—only metric/alert definitions you can create in Cloud Logging / Cloud Monitoring.

---

## Logging primitives (what exists today)

### Consumer (`cloudrun_consumer/`)
Structured JSON is printed per event with stable keys:
- **Identity**: `service`, `env`
- **Event key**: `event_type`
- **Severity**: `severity`
- **Useful fields**: `handler`, `messageId`, `serviceId`, `applied`, `reason`, `error`

Notable `event_type` values:
- **Success**: `materialize.ok`
- **Write/handler failures**:
  - `materialize.exception` (500, triggers retries → eventual DLQ depending on subscription policy)
  - `materialize.bad_event` (400, poison → retries → eventual DLQ depending on subscription policy)
- **Ingress/format failures**:
  - `pubsub.invalid_json`
  - `pubsub.invalid_envelope` (with `reason`)
  - `pubsub.invalid_base64`
  - `pubsub.invalid_payload_json`
  - `pubsub.payload_not_object`
  - `pubsub.unroutable_payload`

### Ingestor (publisher) (`backend/messaging/publisher.py`)
Structured JSON logs via `backend/observability/ops_json_logger.py`:
- `event_type="pubsub_publish_success"` (includes `topic`, `message_id`, `event_type`, `agent_name`, `trace_id`, `attempt`, `elapsed_ms`)
- `event_type="pubsub_publish_failure"` (includes `topic`, `event_type`, `agent_name`, `trace_id`, `attempt`, `max_attempts`, `retryable`, `error_type`, `error_code`, `error`, `elapsed_ms`)

Auth failures show up as publish failures with `error_code` like **`UNAUTHENTICATED`** or **`PERMISSION_DENIED`** (or equivalent `error_type` names).

---

## Proposed log-based metrics (5)

All examples assume **Cloud Logging Log-based metrics** (counter), with filters written in Cloud Logging query syntax.  
Where possible, filter by `resource.type="cloud_run_revision"` and `resource.labels.service_name="<service>"`.

### 1) `pubsub_publish_failures_total`
Counts all publish attempts that ultimately log a failure (including retryable warnings and terminal failures).

**Filter:**
- `resource.type="cloud_run_revision"`
- `jsonPayload.event_type="pubsub_publish_failure"`

**Optional refinement (reduce noise):**
- only terminal failures: `jsonPayload.retryable=false` OR `jsonPayload.attempt=jsonPayload.max_attempts`

### 2) `pubsub_publish_auth_errors_total`
Counts publish failures that are almost certainly credentials/permissions misconfigurations.

**Filter:**
- `resource.type="cloud_run_revision"`
- `jsonPayload.event_type="pubsub_publish_failure"`
- `jsonPayload.error_code=("UNAUTHENTICATED" OR "PERMISSION_DENIED")`

**Fallback if `error_code` is empty in some runtimes:**
- `jsonPayload.error_type=("Unauthenticated" OR "PermissionDenied")`

### 3) `consumer_materialize_exceptions_total`
Counts consumer-side exceptions that return **HTTP 500** (Pub/Sub will retry; can cascade into DLQ).

**Filter:**
- `resource.type="cloud_run_revision"`
- `resource.labels.service_name="cloudrun-pubsub-firestore-materializer"`
- `jsonPayload.event_type="materialize.exception"`

### 4) `consumer_poison_events_total`
Counts poison/unprocessable events (400s and schema/decoding failures) that are highly likely to become DLQ traffic.

**Filter:**
- `resource.type="cloud_run_revision"`
- `resource.labels.service_name="cloudrun-pubsub-firestore-materializer"`
- `(
    jsonPayload.event_type="materialize.bad_event"
    OR jsonPayload.event_type=~"^pubsub\\.invalid_"
    OR jsonPayload.event_type IN ("pubsub.payload_not_object","pubsub.unroutable_payload")
  )`

### 5) `consumer_pubsub_push_non_2xx_total` (DLQ growth proxy)
Counts requests to the Pub/Sub push endpoint that returned non-2xx (these deliveries will be retried and may hit the subscription dead-letter policy).

**Filter (Cloud Run request logs):**
- `resource.type="cloud_run_revision"`
- `resource.labels.service_name="cloudrun-pubsub-firestore-materializer"`
- `httpRequest.requestUrl:"/pubsub/push"`
- `httpRequest.status>=400`

**Notes:**
- This metric is intentionally **log-derived** but based on **request logs**, not app logs, so it still works even if the app crashes before logging.

---

## Proposed alerts (5) with thresholds

These are written as Monitoring alerting policies over the log-based metrics above. Adjust windows to match your SLOs and Pub/Sub retry/DLQ settings.

### 1) Publish failures (rate) — *ingestor*
- **Signal**: `pubsub_publish_failures_total`
- **Condition**:
  - **Warning**: \(\ge 5\) in **5 minutes**
  - **Critical**: \(\ge 20\) in **5 minutes**
- **Why**: catches intermittent Pub/Sub outages, quota/resource exhaustion, misrouted topics.

### 2) Publish auth/permission failures — *ingestor*
- **Signal**: `pubsub_publish_auth_errors_total`
- **Condition**:
  - **Critical**: \(\ge 1\) in **5 minutes**
- **Why**: `UNAUTHENTICATED` / `PERMISSION_DENIED` are almost never transient; they typically require IAM / workload identity / service account remediation.

### 3) Consumer write/handler exceptions — *consumer*
- **Signal**: `consumer_materialize_exceptions_total`
- **Condition**:
  - **Warning**: \(\ge 1\) in **5 minutes**
  - **Critical**: \(\ge 3\) in **5 minutes**
- **Why**: repeated 500s imply Firestore/API instability, schema bugs, or quota; will drive retries and can create backlog/DLQ.

### 4) DLQ growth risk (delivery failures) — *consumer*
- **Signal**: `consumer_pubsub_push_non_2xx_total`
- **Condition**:
  - **Warning**: \(\ge 10\) in **10 minutes**
  - **Critical**: \(\ge 50\) in **10 minutes**
- **Why**: non-2xx responses correlate directly with redelivery attempts and eventual dead-lettering.

### 5) Silent stall (no successful materialization) — *consumer*
- **Signal**: create a *derived* log-based metric for success:
  - `consumer_materialize_ok_total` with filter:
    - `resource.type="cloud_run_revision"`
    - `resource.labels.service_name="cloudrun-pubsub-firestore-materializer"`
    - `jsonPayload.event_type="materialize.ok"`
- **Condition (recommended multi-condition):**
  - **Critical** if:
    - `consumer_materialize_ok_total == 0` for **15 minutes**, **AND**
    - either `consumer_pubsub_push_non_2xx_total > 0` in the same window **OR** Cloud Run request count to `/pubsub/push` is non-zero.
- **Why**: catches “service is up but doing nothing” (stuck subscription, routing change, auth break upstream, or message parsing regression).

---

## Practical runbook notes (fast triage)

- **Publish failures** (`pubsub_publish_failure`):
  - Check `error_code` first: `UNAUTHENTICATED` / `PERMISSION_DENIED` are IAM/WI issues.
  - For `RESOURCE_EXHAUSTED`, look for quota and retry/backoff behavior.
  - Validate `topic` (full topic path) matches expected project/topic.

- **Consumer non-2xx / poison events**:
  - `materialize.bad_event` and `pubsub.invalid_*` are typically **schema/contract issues**; expect DLQ growth unless fixed quickly.
  - `materialize.exception` is typically **dependency/runtime** (Firestore) or code exception; expect redelivery storms if persistent.

- **Silent stalls**:
  - If `materialize.ok` is flatlined but request logs show traffic, focus on spikes in:
    - `consumer_pubsub_push_non_2xx_total`
    - `consumer_poison_events_total`
  - If both success and errors are absent, focus on upstream publishing/subscription routing rather than the consumer.

