from __future__ import annotations

import os

from backend.messaging.publisher import PubSubPublisher


HEARTBEAT_EVENT_TYPE = "marketdata.heartbeat"


def main() -> None:
    """
    Publish a single heartbeat event to Google Pub/Sub.

    Required env vars:
      - PUBSUB_PROJECT_ID
      - PUBSUB_TOPIC_ID
    """

    project_id = os.environ["PUBSUB_PROJECT_ID"]
    topic_id = os.environ["PUBSUB_TOPIC_ID"]

    pub = PubSubPublisher(
        project_id=project_id,
        topic_id=topic_id,
        agent_name="marketdata",
    )

    message_id = pub.publish_event(
        event_type=HEARTBEAT_EVENT_TYPE,
        payload={"status": "ok", "service": "marketdata"},
    )
    print("published message_id:", message_id)


if __name__ == "__main__":
    main()

