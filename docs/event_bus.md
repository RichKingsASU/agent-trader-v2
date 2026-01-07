# Event Bus (Agent-to-Agent) — Google Pub/Sub

This document defines the **agent-to-agent event bus** contract implemented in `backend/messaging/`.

The preferred transport is **Google Pub/Sub**, with a tiny local in-memory option for demos.

## Goals

- **Clean contract**: a single JSON envelope all agents can produce/consume
- **Transport-agnostic interface**: producers/consumers deal in envelopes, not SDK details
- **Deployable later**: Pub/Sub wiring is straightforward once topics/subscriptions exist

## Message envelope (schema)

Every message published on the agent event bus is a UTF-8 JSON object with the following fields:

- **`event_type`**: stable event identifier (example: `"marketdata.heartbeat"`)
- **`agent_name`**: producing agent/service logical name (example: `"marketdata"`)
- **`git_sha`**: git SHA of the producer build (example: `"a1b2c3d..."` or `"unknown"`)
- **`ts`**: producer timestamp (ISO-8601; UTC recommended)
- **`payload`**: JSON object (event-specific payload)
- **`trace_id`**: correlation id for distributed tracing/log stitching

The canonical implementation is `backend/messaging/envelope.py` (`EventEnvelope`).

## Pub/Sub topics and subscriptions

### Topic: `agent-events`

Recommended single topic for all agent events:

- **Topic id**: `agent-events`
- **Data**: full JSON envelope (bytes)
- **Attributes** (duplicated for filtering/debugging):
  - `event_type`
  - `agent_name`
  - `trace_id`
  - `git_sha`
  - `ts`

### Subscriptions

Create one subscription per consumer/agent, for example:

- **`strategy-engine-agent-events`**: strategy-engine reads `agent-events`
- **`market-ingest-agent-events`**: market-ingest reads `agent-events`

If you want routing without separate topics, prefer **subscription filters** on attributes
(e.g. `attributes.event_type="marketdata.heartbeat"`).

## Example: heartbeat events

### Producer (marketdata) publishes heartbeats

- **Event type**: `marketdata.heartbeat`
- **Payload example**:

```json
{
  "status": "ok",
  "service": "marketdata"
}
```

See:
- `backend/messaging/examples/marketdata_publish_heartbeat_pubsub.py`
- `backend/messaging/examples/heartbeat_local_demo.py` (no Pub/Sub)

### Consumer (strategy-engine) subscribes and updates internal state

The consumer reads envelopes, filters by `event_type == "marketdata.heartbeat"`,
and updates an internal `StrategyEngineState`.

See:
- `backend/messaging/examples/strategy_engine_subscribe_heartbeat_pubsub.py`
- `backend/messaging/examples/heartbeat_local_demo.py`

## Local testing

### Option A: no Pub/Sub (local in-memory demo)

Run:

```bash
python -m backend.messaging.examples.heartbeat_local_demo
```

### Option B: Pub/Sub emulator

You can use the Google Pub/Sub emulator to test without GCP credentials.

High-level steps:

1. Start the emulator and set `PUBSUB_EMULATOR_HOST`
2. Create topic + subscription (`agent-events`, `strategy-engine-agent-events`)
3. Run the publisher and subscriber examples

Example environment variables used by the scripts:

- `PUBSUB_PROJECT_ID`
- `PUBSUB_TOPIC_ID`
- `PUBSUB_SUBSCRIPTION_ID`

Dependency:

```bash
pip install google-cloud-pubsub
```

