# Observability & Alerts (Low Noise)

Goal: **Know when things break before users do** without creating alert fatigue.

Scope for this repo:
- **Log-based metrics only** for the requested signals (no dashboards).
- **Cloud Monitoring alert policies** for the three highest-signal failure modes:
  - **zero publishes in 5m**
  - **DLQ growth**
  - **consumer error rate**

This repo already emits structured JSON logs with stable `event_type` fields:
- Publisher: `pubsub_publish_success`, `pubsub_publish_failure` (`backend/messaging/publisher.py`)
- Consumer (Cloud Run push): `materialize.ok` (`cloudrun_consumer/main.py`)

---

## Log-based metrics (Cloud Logging)

### Metrics to create

- **`publish_success`** (counter): counts successful publishes
  - Filter: `jsonPayload.event_type="pubsub_publish_success"`
- **`publish_failure`** (counter): counts **terminal** publish failures (low noise)
  - Filter: `jsonPayload.event_type="pubsub_publish_failure" AND severity="ERROR"`
  - Note: retryable failures are logged as `WARNING`; excluding them avoids paging on self-healing retries.
- **`consumer_ack`** (counter): counts successful consumer handling (“ack” equivalent)
  - Filter: `jsonPayload.event_type="materialize.ok"`

Each metric includes low-cardinality labels to support targeted alerting:
- `service` (producer service name)
- `env` (environment)
- `topic` (Pub/Sub topic path or inferred topic when logged)

### gcloud commands (create log-based metrics)

Set your project first:

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
gcloud config set project "$PROJECT_ID"
```

Create `publish_success`:

```bash
gcloud logging metrics create publish_success \
  --config-from-file=<(cat <<'JSON'
{
  "name": "publish_success",
  "description": "Count of successful Pub/Sub publishes (pubsub_publish_success).",
  "filter": "resource.type=\"cloud_run_revision\" AND jsonPayload.event_type=\"pubsub_publish_success\"",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1",
    "labels": [
      { "key": "service", "valueType": "STRING", "description": "Emitting service name (jsonPayload.service)." },
      { "key": "env", "valueType": "STRING", "description": "Environment label (jsonPayload.env)." },
      { "key": "topic", "valueType": "STRING", "description": "Pub/Sub topic path when logged (jsonPayload.topic)." }
    ]
  },
  "labelExtractors": {
    "service": "EXTRACT(jsonPayload.service)",
    "env": "EXTRACT(jsonPayload.env)",
    "topic": "EXTRACT(jsonPayload.topic)"
  }
}
JSON
)
```

Create `publish_failure` (terminal only, `severity=ERROR`):

```bash
gcloud logging metrics create publish_failure \
  --config-from-file=<(cat <<'JSON'
{
  "name": "publish_failure",
  "description": "Count of terminal Pub/Sub publish failures (pubsub_publish_failure at severity=ERROR).",
  "filter": "resource.type=\"cloud_run_revision\" AND jsonPayload.event_type=\"pubsub_publish_failure\" AND severity=\"ERROR\"",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1",
    "labels": [
      { "key": "service", "valueType": "STRING", "description": "Emitting service name (jsonPayload.service)." },
      { "key": "env", "valueType": "STRING", "description": "Environment label (jsonPayload.env)." },
      { "key": "topic", "valueType": "STRING", "description": "Pub/Sub topic path when logged (jsonPayload.topic)." }
    ]
  },
  "labelExtractors": {
    "service": "EXTRACT(jsonPayload.service)",
    "env": "EXTRACT(jsonPayload.env)",
    "topic": "EXTRACT(jsonPayload.topic)"
  }
}
JSON
)
```

Create `consumer_ack`:

```bash
gcloud logging metrics create consumer_ack \
  --config-from-file=<(cat <<'JSON'
{
  "name": "consumer_ack",
  "description": "Count of successful consumer processing (materialize.ok).",
  "filter": "resource.type=\"cloud_run_revision\" AND jsonPayload.event_type=\"materialize.ok\"",
  "metricDescriptor": {
    "metricKind": "DELTA",
    "valueType": "INT64",
    "unit": "1",
    "labels": [
      { "key": "service", "valueType": "STRING", "description": "Emitting service name (jsonPayload.service)." },
      { "key": "env", "valueType": "STRING", "description": "Environment label (jsonPayload.env)." },
      { "key": "topic", "valueType": "STRING", "description": "Inferred source topic when logged (jsonPayload.topic)." }
    ]
  },
  "labelExtractors": {
    "service": "EXTRACT(jsonPayload.service)",
    "env": "EXTRACT(jsonPayload.env)",
    "topic": "EXTRACT(jsonPayload.topic)"
  }
}
JSON
)
```

Verify metrics exist:

```bash
gcloud logging metrics list --format="table(name,description)"
```

---

## Cloud Monitoring alert policies (low noise)

### Shared setup

You’ll need an existing notification channel (email, PagerDuty, Slack, etc.). Keep it out of this repo and reference it by ID.

```bash
gcloud alpha monitoring channels list --format="table(name,type,displayName)"
export NOTIFICATION_CHANNEL_ID="YOUR_CHANNEL_RESOURCE_NAME"
```

#### Low-noise defaults used below
- **Rate-limit notifications**: at most one notification every 30–60 minutes per policy.
- **Auto-close**: close incidents automatically after stability (prevents “stuck open” incidents).
- **Scope tightly**: restrict to `env="prod"` and only services that should be continuously publishing.

---

### Alert 1: Zero publishes in 5 minutes

Use this ONLY for producers that are expected to publish continuously (e.g., market ingest), not cron-like jobs.

```bash
export PUBLISHER_SERVICE_NAME="YOUR_PUBLISHER_CLOUD_RUN_SERVICE"
export ENV_LABEL="prod"

gcloud alpha monitoring policies create \
  --policy-from-file=<(cat <<JSON
{
  "displayName": "Publisher stalled: zero publishes (5m)",
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["'"$NOTIFICATION_CHANNEL_ID"'"],
  "alertStrategy": {
    "notificationRateLimit": { "period": "1800s" },
    "autoClose": "86400s"
  },
  "conditions": [
    {
      "displayName": "No publish_success points for 5m",
      "conditionAbsent": {
        "filter": "metric.type=\"logging.googleapis.com/user/publish_success\" AND metric.label.service=\"'"$PUBLISHER_SERVICE_NAME"'\" AND metric.label.env=\"'"$ENV_LABEL"'\"",
        "duration": "300s",
        "trigger": { "count": 1 },
        "aggregations": [
          { "alignmentPeriod": "60s", "perSeriesAligner": "ALIGN_SUM" }
        ]
      }
    }
  ],
  "documentation": {
    "mimeType": "text/markdown",
    "content": "## What this means\\nThe publisher emitted **zero successful publishes** for 5 minutes.\\n\\n## Fast triage\\n- Check Cloud Run errors/restarts for the publisher service\\n- Search logs for `pubsub_publish_failure` and its `error_code` (PERMISSION_DENIED / UNAUTHENTICATED / NOT_FOUND are high-signal)\\n- Validate topic configuration and IAM for the publisher service account\\n"
  }
}
JSON
)
```

---

### Alert 2: DLQ growth

Prefer **native Pub/Sub metrics** (lower noise and not dependent on application logs).

```bash
export DLQ_SUBSCRIPTION_ID="YOUR_DLQ_SUBSCRIPTION_ID"

gcloud alpha monitoring policies create \
  --policy-from-file=<(cat <<JSON
{
  "displayName": "DLQ growing (Pub/Sub)",
  "combiner": "OR",
  "enabled": true,
  "notificationChannels": ["'"$NOTIFICATION_CHANNEL_ID"'"],
  "alertStrategy": {
    "notificationRateLimit": { "period": "3600s" },
    "autoClose": "86400s"
  },
  "conditions": [
    {
      "displayName": "DLQ has any undelivered messages for 10m",
      "conditionThreshold": {
        "filter": "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\" AND resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"'"$DLQ_SUBSCRIPTION_ID"'\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0,
        "duration": "600s",
        "trigger": { "count": 1 },
        "aggregations": [
          { "alignmentPeriod": "60s", "perSeriesAligner": "ALIGN_MAX" }
        ]
      }
    },
    {
      "displayName": "DLQ is clearly accumulating (>=10 msgs for 10m)",
      "conditionThreshold": {
        "filter": "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\" AND resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"'"$DLQ_SUBSCRIPTION_ID"'\"",
        "comparison": "COMPARISON_GE",
        "thresholdValue": 10,
        "duration": "600s",
        "trigger": { "count": 1 },
        "aggregations": [
          { "alignmentPeriod": "60s", "perSeriesAligner": "ALIGN_MAX" }
        ]
      }
    }
  ],
  "documentation": {
    "mimeType": "text/markdown",
    "content": "## What this means\\nMessages are landing in the DLQ and not being drained.\\n\\n## Fast triage\\n- Check consumer error rate (5xx) and logs for `materialize.exception` / `materialize.bad_event`\\n- If predominantly 4xx/poison: likely producer contract/schema break\\n- If predominantly 5xx: dependency/quota/outage (e.g., Firestore)\\n\\n## Action\\nFix root cause first, then replay/drain DLQ with idempotency safeguards.\\n"
  }
}
JSON
)
```

---

### Alert 3: Consumer error rate (Cloud Run 5xx ratio)

This captures “consumer is failing to ack” without depending on application log completeness.

```bash
export CONSUMER_SERVICE_NAME="cloudrun-pubsub-firestore-materializer"

gcloud alpha monitoring policies create \
  --policy-from-file=<(cat <<JSON
{
  "displayName": "Consumer elevated 5xx rate (Pub/Sub push)",
  "combiner": "AND",
  "enabled": true,
  "notificationChannels": ["'"$NOTIFICATION_CHANNEL_ID"'"],
  "alertStrategy": {
    "notificationRateLimit": { "period": "1800s" },
    "autoClose": "86400s"
  },
  "conditions": [
    {
      "displayName": "5xx ratio > 5% for 10m",
      "conditionThreshold": {
        "filter": "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"'"$CONSUMER_SERVICE_NAME"'\" AND metric.labels.response_code_class=\"5xx\"",
        "denominatorFilter": "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"'"$CONSUMER_SERVICE_NAME"'\"",
        "comparison": "COMPARISON_GT",
        "thresholdValue": 0.05,
        "duration": "600s",
        "trigger": { "count": 1 },
        "aggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM",
            "groupByFields": []
          }
        ],
        "denominatorAggregations": [
          {
            "alignmentPeriod": "60s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM",
            "groupByFields": []
          }
        ]
      }
    },
    {
      "displayName": "Traffic gate: >= 20 requests per 10m",
      "conditionThreshold": {
        "filter": "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"'"$CONSUMER_SERVICE_NAME"'\"",
        "comparison": "COMPARISON_GE",
        "thresholdValue": 20,
        "duration": "600s",
        "trigger": { "count": 1 },
        "aggregations": [
          {
            "alignmentPeriod": "600s",
            "perSeriesAligner": "ALIGN_SUM",
            "crossSeriesReducer": "REDUCE_SUM",
            "groupByFields": []
          }
        ]
      }
    }
  ],
  "documentation": {
    "mimeType": "text/markdown",
    "content": "## What this means\\nThe consumer is returning elevated 5xx responses (Pub/Sub will retry; backlog/DLQ risk).\\n\\n## Fast triage\\n- Check recent deploys + Cloud Run resource pressure (OOM, timeouts)\\n- Inspect consumer logs for `materialize.exception` spikes and Firestore-related errors\\n- If Firestore/quota: reduce write pressure or increase quotas; if code regression: rollback/fix\\n"
  }
}
JSON
)
```

---

## Notes on “alert fatigue avoided”

- **Zero publishes**: scope only to continuous publishers; otherwise it will false-alert during expected idle.
- **Publish failure metric**: counts only `severity=ERROR` terminal failures (retry noise excluded).
- **DLQ growth**: uses native Pub/Sub metrics; alerts only when there is sustained accumulation.
- **Consumer error rate**: ratio-based and traffic-gated (`total >= 20` per minute in the MQL) to avoid noisy alerts during low traffic.

