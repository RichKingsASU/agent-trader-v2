from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from backend.messaging.local import InMemoryEventBus


HEARTBEAT_EVENT_TYPE = "marketdata.heartbeat"
TOPIC_AGENT_EVENTS = "agent-events"


@dataclass
class StrategyEngineState:
    last_marketdata_heartbeat_ts: str | None = None
    last_marketdata_heartbeat_payload: Dict[str, Any] | None = None
    last_trace_id: str | None = None

    def on_envelope(self, envelope: Any) -> None:
        if envelope.event_type != HEARTBEAT_EVENT_TYPE:
            return
        self.last_marketdata_heartbeat_ts = envelope.ts
        self.last_marketdata_heartbeat_payload = dict(envelope.payload or {})
        self.last_trace_id = envelope.trace_id


def main() -> None:
    """
    Local-only demo (no Pub/Sub required):
      - marketdata publishes a heartbeat event
      - strategy-engine consumes and updates internal state
    """

    bus = InMemoryEventBus()

    # marketdata publishes heartbeat
    bus.publish(
        topic=TOPIC_AGENT_EVENTS,
        event_type=HEARTBEAT_EVENT_TYPE,
        agent_name="marketdata",
        payload={"status": "ok", "service": "marketdata"},
    )

    # strategy-engine subscribes (simulated by draining topic)
    state = StrategyEngineState()
    for env in bus.drain(topic=TOPIC_AGENT_EVENTS):
        state.on_envelope(env)

    # "internal state" is updated
    print("StrategyEngineState:", state)


if __name__ == "__main__":
    main()

