from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict

from backend.messaging.subscriber import PubSubSubscriber
from backend.common.ops_log import log_json


HEARTBEAT_EVENT_TYPE = "marketdata.heartbeat"


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
        log_json(
            intent_type="pubsub.heartbeat_received",
            severity="INFO",
            iteration_id=envelope.trace_id,
            ts=envelope.ts,
            payload=self.last_marketdata_heartbeat_payload,
        )


def main() -> None:
    """
    Subscribe to heartbeat events from Google Pub/Sub and update state.

    Required env vars:
      - PUBSUB_PROJECT_ID
      - PUBSUB_SUBSCRIPTION_ID
    """

    project_id = os.environ["PUBSUB_PROJECT_ID"]
    sub_id = os.environ["PUBSUB_SUBSCRIPTION_ID"]

    state = StrategyEngineState()

    sub = PubSubSubscriber(project_id=project_id, subscription_id=sub_id)
    future = sub.subscribe(state.on_envelope)

    log_json(
        intent_type="pubsub.subscribed",
        severity="INFO",
        subscription_id=sub_id,
        project_id=project_id,
        event_type=HEARTBEAT_EVENT_TYPE,
    )
    try:
        future.result()
    except KeyboardInterrupt:
        future.cancel()


if __name__ == "__main__":
    main()

