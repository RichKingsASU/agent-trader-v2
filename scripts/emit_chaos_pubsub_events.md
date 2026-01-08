## Chaos Pub/Sub event generator

This repo includes a small generator to emit **valid test events** and **chaos/edge-case events** against the Cloud Run consumer endpoint:

- Consumer: `cloudrun_consumer/main.py`
- Endpoint: `POST /pubsub/push`

The script can either:

- Print Pub/Sub push envelopes to stdout (**dry-run**), or
- POST them to a running service and print the HTTP result (1 line per event).

### Prerequisites (run consumer locally)

From repo root:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r cloudrun_consumer/requirements.txt

export GCP_PROJECT="your-gcp-project"
export ENV="staging"
export SYSTEM_EVENTS_TOPIC="system.events"
export DEFAULT_REGION="us-central1"

python3 cloudrun_consumer/main.py
```

The consumer will listen on `http://localhost:8080`.

### Emit valid events

Emit one valid **topic-routed** event (defaults to `market-ticks`):

```bash
python3 scripts/emit_chaos_pubsub_events.py --scenario valid_topic_event --topic market-ticks
```

Emit a valid **system event** (routes by payload shape: `service` + `timestamp`):

```bash
python3 scripts/emit_chaos_pubsub_events.py --scenario valid_system_event
```

### Emit chaos / edge cases

Envelope-level validation failures (expect **HTTP 400**, no crash):

```bash
python3 scripts/emit_chaos_pubsub_events.py --scenario missing_messageId
python3 scripts/emit_chaos_pubsub_events.py --scenario missing_data
python3 scripts/emit_chaos_pubsub_events.py --scenario invalid_base64
python3 scripts/emit_chaos_pubsub_events.py --scenario invalid_payload_json
python3 scripts/emit_chaos_pubsub_events.py --scenario payload_not_object
```

Routing/handler edge cases (expect **HTTP 400**):

```bash
python3 scripts/emit_chaos_pubsub_events.py --scenario unroutable_payload
python3 scripts/emit_chaos_pubsub_events.py --scenario system_event_blank_service
python3 scripts/emit_chaos_pubsub_events.py --scenario system_event_invalid_producedAt
```

Old schema / legacy shapes (valid JSON that should be **rejected** or **handled flexibly**, depending on topic routing):

```bash
# Old agent envelope wrapper (usually unroutable -> 400)
python3 scripts/emit_chaos_pubsub_events.py --scenario old_schema_agent_envelope_wrapped

# PubSubEvent wrapper (accepted via topic routing; stored mostly verbatim)
python3 scripts/emit_chaos_pubsub_events.py --scenario old_schema_pubsub_event_wrapped --topic trade-signals
```

### Dry-run (print envelopes without sending)

```bash
python3 scripts/emit_chaos_pubsub_events.py --dry-run --pretty --scenario valid_topic_event --topic market-bars-1m
```

### Notes on “graceful handling”

- “Bad” envelopes should return **HTTP 400** (so Pub/Sub can route them to a DLQ, if configured).
- The generator keeps events as **valid JSON** so failures are focused on schema/field-edge handling, not transport.

