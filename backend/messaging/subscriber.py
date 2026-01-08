from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from backend.messaging.envelope import EventEnvelope


EnvelopeHandler = Callable[[EventEnvelope], None]


@dataclass(frozen=True, slots=True)
class ReceivedMessage:
    envelope: EventEnvelope
    message_id: str
    publish_time: Optional[str]


class PubSubSubscriber:
    """
    Google Pub/Sub subscriber for agent events.

    Lazy-imports `google.cloud.pubsub_v1` so the codebase can still import/compile
    in environments where Pub/Sub dependencies are not installed yet.
    """

    def __init__(
        self,
        *,
        project_id: str,
        subscription_id: str,
        subscriber_client: Any = None,
    ) -> None:
        self.project_id = str(project_id)
        self.subscription_id = str(subscription_id)

        if subscriber_client is None:
            try:
                from google.cloud import pubsub_v1  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError(
                    "google-cloud-pubsub is required to use PubSubSubscriber. "
                    "Install with: pip install google-cloud-pubsub"
                ) from e
            subscriber_client = pubsub_v1.SubscriberClient()

        self._client = subscriber_client
        self._subscription_path = self._client.subscription_path(
            self.project_id, self.subscription_id
        )

    @property
    def subscription_path(self) -> str:
        return self._subscription_path

    def subscribe(self, handler: EnvelopeHandler) -> Any:
        """
        Start a streaming pull subscription.

        Returns the Pub/Sub StreamingPullFuture.

        NOTE: The caller owns lifecycle management (future.cancel(), etc).
        """

        def _callback(message: Any) -> None:
            try:
                envelope = EventEnvelope.from_bytes(message.data)
                if int(getattr(envelope, "schemaVersion", 0) or 0) != 1:
                    raise ValueError(f"Unsupported schemaVersion for EventEnvelope: {getattr(envelope, 'schemaVersion', None)}")
                handler(envelope)
                message.ack()
            except Exception:
                # Prefer retry for transient errors / handler exceptions.
                message.nack()

        return self._client.subscribe(self._subscription_path, callback=_callback)

