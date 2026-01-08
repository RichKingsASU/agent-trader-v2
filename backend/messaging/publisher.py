from __future__ import annotations

from typing import Any, Mapping, Optional

from backend.messaging.envelope import EventEnvelope


class PubSubPublisher:
    """
    Google Pub/Sub publisher for agent events.

    Lazy-imports `google.cloud.pubsub_v1` so the codebase can still import/compile
    in environments where Pub/Sub dependencies are not installed yet.
    """

    def __init__(
        self,
        *,
        project_id: str,
        topic_id: str,
        agent_name: str,
        git_sha: Optional[str] = None,
        publisher_client: Any = None,
    ) -> None:
        self.project_id = str(project_id)
        self.topic_id = str(topic_id)
        self.agent_name = str(agent_name)
        self.git_sha = git_sha

        if publisher_client is None:
            try:
                from google.cloud import pubsub_v1  # type: ignore
            except Exception as e:  # pragma: no cover
                raise RuntimeError(
                    "google-cloud-pubsub is required to use PubSubPublisher. "
                    "Install with: pip install google-cloud-pubsub"
                ) from e
            publisher_client = pubsub_v1.PublisherClient()

        self._client = publisher_client
        self._topic_path = self._client.topic_path(self.project_id, self.topic_id)

    @property
    def topic_path(self) -> str:
        return self._topic_path

    def publish_envelope(self, envelope: EventEnvelope) -> str:
        """
        Publish a fully-formed envelope.

        Returns a Pub/Sub message id (string).
        """

        future = self._client.publish(
            self._topic_path,
            envelope.to_bytes(),
            # Also duplicate key fields as attributes for filtering/debugging.
            event_type=envelope.event_type,
            agent_name=envelope.agent_name,
            trace_id=envelope.trace_id,
            git_sha=envelope.git_sha,
            ts=envelope.ts,
        )
        return str(future.result())

    def publish_event(
        self,
        *,
        event_type: str,
        payload: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> str:
        envelope = EventEnvelope.new(
            event_type=event_type,
            agent_name=self.agent_name,
            git_sha=self.git_sha,
            payload=payload,
            trace_id=trace_id,
        )
        return self.publish_envelope(envelope)

    def close(self) -> None:
        """
        Best-effort shutdown for the underlying Pub/Sub client.

        Rationale: PublisherClient can own background threads/batching and gRPC channels.
        This method is intentionally defensive across google-cloud-pubsub versions.
        """
        client = getattr(self, "_client", None)
        if client is None:
            return

        # Stop background batching threads (older versions).
        try:
            stop = getattr(client, "stop", None)
            if callable(stop):
                stop()
        except Exception:
            pass

        # Close transport / channels (newer versions).
        try:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except Exception:
            pass

        try:
            transport = getattr(client, "transport", None)
            transport_close = getattr(transport, "close", None)
            if callable(transport_close):
                transport_close()
        except Exception:
            pass

    def __enter__(self) -> "PubSubPublisher":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

