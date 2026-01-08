# Alert Recommendations v1 (Cloud Logging / Cloud Monitoring)

This document defines **recommended alerting policies** for the ingestion → messaging → consumer pipeline:
- **Ingestor**: Cloud Run services publishing to Pub/Sub (logs `jsonPayload.event_type="pubsub_publish_failure"` from `backend/messaging/publisher.py`).
- **Consumer**: Cloud Run Pub/Sub push consumer(s) writing to Firestore (notably the system-events materializer).

All alerts below include:
- **alert name**
- **signal**
- **threshold**
- **notification severity**
- **runbook steps**

Notes:
- Prefer **native service metrics** (Cloud Run / Pub/Sub / Firestore) when available; use **log-based metrics** when the service metric can’t classify the failure mode.
- Replace placeholders like `<INGESTOR_SERVICE>`, `<CONSUMER_SERVICE>`, `<SUBSCRIPTION_ID>`, `<DLQ_SUBSCRIPTION_ID>`, and `<PROJECT_ID>` with your actual values.
- See also: `docs/logging_alerts_v1.md`, `docs/dlq_and_retries.md`, `docs/runbooks/heartbeat.md`.

---

## Alert 1 — Ingestor publish failure: PERMISSION_DENIED

- **alert name**: `Ingestor Pub/Sub publish permission denied`
- **signal**: Log-based metric (counter) from Cloud Logging
  - **Filter (recommended)**:
    - `resource.type="cloud_run_revision"`
    - `resource.labels.service_name="<INGESTOR_SERVICE>"`
    - `jsonPayload.event_type="pubsub_publish_failure"`
    - `jsonPayload.error_code="PERMISSION_DENIED"`
  - **Fallback filter (if `error_code` not present)**:
    - add: `jsonPayload.error_type=("PermissionDenied" OR "Forbidden")`
    - or: `jsonPayload.error:"PERMISSION_DENIED"`
- **threshold**:
  - **Critical**: ≥ **1** event in **5 minutes**
- **notification severity**: **SEV-1 (page)**
- **runbook steps**:
  - **Confirm scope**: In Logs Explorer, open one failing entry and capture `topic`, `trace_id` (if present), and the publishing service revision.
  - **Validate IAM**:
    - Identify the ingestor’s runtime identity (Cloud Run service account).
    - Ensure it has Pub/Sub publish permissions on the target topic (typically `roles/pubsub.publisher` on the topic or project).
  - **Validate topic/project**:
    - Confirm the topic is in the intended `<PROJECT_ID>` and the ingestor is not accidentally pointing at a different project/topic.
  - **Check recent changes**:
    - Look for IAM changes, service account rotation, Workload Identity / federation changes, or environment variable changes affecting topic names.
  - **Mitigate**:
    - Restore required IAM bindings and redeploy/restart the service if tokens/credentials need refresh.
  - **Verify recovery**:
    - Confirm `pubsub_publish_success` logs resume and the alert clears within one evaluation window.

---

## Alert 2 — Ingestor publish failure: NOT_FOUND

- **alert name**: `Ingestor Pub/Sub publish not found`
- **signal**: Log-based metric (counter) from Cloud Logging
  - **Filter (recommended)**:
    - `resource.type="cloud_run_revision"`
    - `resource.labels.service_name="<INGESTOR_SERVICE>"`
    - `jsonPayload.event_type="pubsub_publish_failure"`
    - `jsonPayload.error_code="NOT_FOUND"`
  - **Fallback filter**:
    - `jsonPayload.error_type=("NotFound")` or `jsonPayload.error:"NOT_FOUND"`
- **threshold**:
  - **Critical**: ≥ **1** event in **5 minutes**
- **notification severity**: **SEV-2 (urgent)**
- **runbook steps**:
  - **Confirm the failing topic**: From the log entry, copy `topic` (full topic path if logged).
  - **Validate topic existence**:
    - Check that the topic exists in the expected project and region context (Pub/Sub is global, but projects/environments differ).
  - **Check configuration drift**:
    - Confirm the ingestor’s topic config (env var / config file) matches the deployed environment.
    - Look for typos, renamed topics, or environment pointing at a deleted/non-provisioned topic.
  - **Mitigate**:
    - Create/restore the missing topic or fix the ingestor configuration to the correct topic.
  - **Verify recovery**:
    - Confirm new publishes succeed and backlog/latency returns to normal.

---

## Alert 3 — Ingestor publish failure: DEADLINE_EXCEEDED

- **alert name**: `Ingestor Pub/Sub publish deadline exceeded`
- **signal**: Log-based metric (counter) from Cloud Logging
  - **Filter (recommended)**:
    - `resource.type="cloud_run_revision"`
    - `resource.labels.service_name="<INGESTOR_SERVICE>"`
    - `jsonPayload.event_type="pubsub_publish_failure"`
    - `jsonPayload.error_code="DEADLINE_EXCEEDED"`
  - **Fallback filter**:
    - `jsonPayload.error_type=("DeadlineExceeded")` or `jsonPayload.error:"DEADLINE_EXCEEDED"`
- **threshold**:
  - **Warning**: ≥ **5** events in **10 minutes**
  - **Critical**: ≥ **20** events in **10 minutes**
- **notification severity**:
  - **Warning**: **SEV-3 (ticket)**
  - **Critical**: **SEV-2 (urgent)**
- **runbook steps**:
  - **Assess blast radius**:
    - Check whether failures affect one ingestor revision or multiple services.
  - **Check Cloud Run health**:
    - Look for CPU/memory saturation, high request latency, or cold-start churn on the ingestor.
  - **Check Pub/Sub health/quota**:
    - Review Pub/Sub quotas (publish requests / throughput) and recent incidents.
  - **Inspect retry behavior**:
    - In logs, compare `attempt`, `max_attempts`, and `elapsed_ms` (if present) to see if retries are succeeding eventually or failing terminally.
  - **Mitigate**:
    - If load-related, increase Cloud Run resources or concurrency limits and/or reduce publish batch sizes.
    - If quota-related, request quota increase or smooth burst behavior.
  - **Verify recovery**:
    - Confirm publish failure rate returns to baseline and downstream consumer backlog clears.

---

## Alert 4 — Consumer Firestore write errors

- **alert name**: `Consumer Firestore write errors`
- **signal**: Prefer Firestore API metrics; supplement with consumer logs for context
  - **Primary (Cloud Monitoring / Firestore)**:
    - Metric: `firestore.googleapis.com/api/request_count`
    - Filter suggestions:
      - `method` in (write paths): `google.firestore.v1.Firestore.Commit`, `google.firestore.v1.Firestore.Write`, `google.firestore.v1.Firestore.BatchWrite`
      - `response_code_class != "2xx"` (or focus on `"5xx"` for transient)
      - (Optional) restrict to the consumer’s service account if label is available in your metric set; otherwise scope by project/env.
  - **Secondary (Cloud Logging / consumer structured logs)**:
    - Log-based metric with filter:
      - `resource.type="cloud_run_revision"`
      - `resource.labels.service_name="<CONSUMER_SERVICE>"`
      - `jsonPayload.event_type="materialize.exception"`
      - AND one of:
        - `jsonPayload.error:"google.api_core.exceptions"` (Python)
        - `jsonPayload.error:("Firestore" OR "firestore")`
        - `jsonPayload.error_code IN ("PERMISSION_DENIED","UNAUTHENTICATED","RESOURCE_EXHAUSTED","UNAVAILABLE","ABORTED","DEADLINE_EXCEEDED")` (if emitted)
- **threshold** (starting defaults; tune to baseline):
  - **Warning**: Firestore non-2xx write requests ≥ **5/min** for **10 minutes**
  - **Critical**: Firestore non-2xx write requests ≥ **20/min** for **10 minutes**
  - **Special-case Critical**: any `PERMISSION_DENIED` or `UNAUTHENTICATED` write error ≥ **1** in **5 minutes**
- **notification severity**:
  - **Warning**: **SEV-3 (ticket)**
  - **Critical**: **SEV-2 (urgent)** (or **SEV-1** for auth failures if it halts ingestion)
- **runbook steps**:
  - **Classify error**:
    - **Permission/auth** (`PERMISSION_DENIED`, `UNAUTHENTICATED`): likely IAM / service account / workload identity issue.
    - **Quota/saturation** (`RESOURCE_EXHAUSTED`, 429): likely Firestore write limits, hot documents, or global quota.
    - **Transient infra** (`UNAVAILABLE`, `DEADLINE_EXCEEDED`): temporary Firestore/service disruption or networking.
    - **Contention** (`ABORTED`): transaction contention or hot-spotting.
  - **Check consumer impact**:
    - If the consumer returns non-2xx on write failures, Pub/Sub will retry and may drive backlog/DLQ.
  - **Inspect recent deploys/config**:
    - Look for changes in document paths, transaction shapes, write amplification, or new high-frequency writers.
  - **Mitigate**:
    - For quota: reduce write rate, shard hot docs, batch writes where safe, or request quota increases.
    - For contention: reduce transaction scope, avoid high-contention counters, introduce sharded counters.
    - For auth: fix IAM (Firestore roles) and redeploy/restart service to refresh tokens.
  - **Verify recovery**:
    - Firestore error rate back to baseline; consumer 5xx/backlog/DLQ alerts should clear shortly after.

---

## Alert 5 — Consumer elevated 5xx rate (Pub/Sub push endpoint)

- **alert name**: `Consumer 5xx rate elevated`
- **signal**: Cloud Run request metric (preferred)
  - Metric: `run.googleapis.com/request_count`
  - Filter:
    - `resource.type="cloud_run_revision"`
    - `resource.labels.service_name="<CONSUMER_SERVICE>"`
    - (Optional) `metric.labels.response_code_class="5xx"`
  - Condition type: **ratio** = 5xx / all requests (same service)
- **threshold**:
  - **Warning**: 5xx ratio > **1%** for **5 minutes** AND request rate ≥ **1 req/min**
  - **Critical**: 5xx ratio > **5%** for **5 minutes** AND request rate ≥ **1 req/min**
- **notification severity**:
  - **Warning**: **SEV-3 (ticket)**
  - **Critical**: **SEV-2 (urgent)**
- **runbook steps**:
  - **Confirm it’s the Pub/Sub push path**:
    - Break down by URL/path if available, or cross-check logs with `httpRequest.requestUrl:"/pubsub/push"`.
  - **Identify dominant failure mode**:
    - Look for correlated spikes in `materialize.exception` (app exceptions) vs platform errors (OOM, timeouts).
  - **Check dependencies**:
    - Firestore errors (Alert 4), external API timeouts, or downstream service failures often manifest as 5xx.
  - **Mitigate**:
    - If resource pressure: increase memory/CPU, adjust concurrency, reduce payload size, or add backpressure.
    - If dependency outage: apply circuit breakers / retries (as appropriate), or temporarily reduce publish volume.
  - **Verify recovery**:
    - 5xx ratio returns to baseline and Pub/Sub backlog stops growing.

---

## Alert 6 — Pub/Sub DLQ growth for `system-events` subscription

- **alert name**: `System-events DLQ growing`
- **signal**: Pub/Sub subscription metrics (Cloud Monitoring)
  - **Primary (DLQ subscription backlog)**:
    - Metric: `pubsub.googleapis.com/subscription/num_undelivered_messages`
    - Resource: `pubsub_subscription`
    - Filter: `resource.labels.subscription_id="<DLQ_SUBSCRIPTION_ID>"`
  - **Secondary (DLQ oldest message age)**:
    - Metric: `pubsub.googleapis.com/subscription/oldest_unacked_message_age`
    - Filter: `resource.labels.subscription_id="<DLQ_SUBSCRIPTION_ID>"`
  - **Optional (main subscription dead-lettering)**:
    - Metric (if enabled in your environment): `pubsub.googleapis.com/subscription/dead_letter_message_count`
    - Filter: `resource.labels.subscription_id="<SUBSCRIPTION_ID>"`
- **threshold**:
  - **Warning**: DLQ undelivered messages > **0** for **10 minutes**
  - **Critical**: DLQ undelivered messages ≥ **10** for **10 minutes** OR oldest unacked age > **30 minutes**
- **notification severity**:
  - **Warning**: **SEV-3 (ticket)**
  - **Critical**: **SEV-2 (urgent)**
- **runbook steps**:
  - **Confirm DLQ routing is active**:
    - Verify `<SUBSCRIPTION_ID>` has a dead-letter policy and points at the DLQ topic; confirm `<DLQ_SUBSCRIPTION_ID>` exists to observe backlog.
  - **Identify why messages are dead-lettering**:
    - Inspect consumer logs around the same timeframe:
      - 4xx indicates schema/contract/poison payloads (often producer-side change).
      - 5xx indicates transient failures (often dependency/quota).
  - **Triage & mitigate**:
    - If poison: coordinate producer rollback/fix; consider pausing publishing if it’s flooding.
    - If transient: resolve dependency issues first (Firestore/quota), then allow replay.
  - **Replay plan**:
    - Once fixed, drain DLQ by replaying messages (mechanism depends on your ops process; ensure idempotency).
  - **Verify recovery**:
    - DLQ backlog decreases steadily; main subscription backlog/oldest age returns to baseline.

---

## Alert 7 — Silent stall: no heartbeat processed for > N minutes

- **alert name**: `Heartbeat not processed (silent stall)`
- **signal**: Log-based metric (counter) + “metric absence” alerting
  - **Log-based metric**: `heartbeat_processed_total`
  - **Recommended filter** (choose the heartbeat signal your system emits):
    - **Option A (application event log)**:
      - `resource.type="cloud_run_revision"`
      - `resource.labels.service_name="<CONSUMER_SERVICE>"`
      - `jsonPayload.event_type=("ingest.heartbeat.applied" OR "heartbeat.processed" OR "materialize.heartbeat.ok")`
    - **Option B (if heartbeat uses existing `materialize.ok` with a subtype/handler)**:
      - `resource.type="cloud_run_revision"`
      - `resource.labels.service_name="<CONSUMER_SERVICE>"`
      - `jsonPayload.event_type="materialize.ok"`
      - `jsonPayload.handler:"heartbeat"` (or another stable discriminator)
  - **Alert condition**: Monitoring “**metric absence**” / “no data”:
    - Trigger when `heartbeat_processed_total` is **absent / zero** for **N minutes**
- **threshold**:
  - **Warning**: no heartbeat processed for **N = 10 minutes**
  - **Critical**: no heartbeat processed for **N = 20 minutes**
- **notification severity**:
  - **Warning**: **SEV-3 (ticket)**
  - **Critical**: **SEV-2 (urgent)** (upgrade to **SEV-1** if heartbeat gates trading safety)
- **runbook steps**:
  - **Confirm whether traffic exists**:
    - Check Pub/Sub subscription metrics for the heartbeat subscription (backlog/oldest age).
    - Check Cloud Run request count to `/pubsub/push` for the relevant consumer.
  - **Branch on what you see**:
    - **Backlog growing**: consumer is failing or slow; investigate consumer 5xx (Alert 5) and Firestore write errors (Alert 4).
    - **No backlog + no heartbeats**: upstream publisher may be down or misconfigured; investigate ingestor publish failures (Alerts 1–3).
    - **Requests arriving but no heartbeat logs**: likely parsing/routing regression; inspect `pubsub.invalid_*`, `materialize.bad_event`, and router logs.
  - **Check the “basic liveness” heartbeat**:
    - If you also run Kubernetes ops heartbeats, follow `docs/runbooks/heartbeat.md` to ensure core services are alive (this helps distinguish “system down” vs “pipeline stalled”).
  - **Mitigate**:
    - Fix the blocking issue (IAM/topic/subscription, consumer exception, Firestore saturation) then verify heartbeat resumes.
  - **Verify recovery**:
    - Heartbeat metric resumes at expected cadence; backlog/oldest age returns to normal.

