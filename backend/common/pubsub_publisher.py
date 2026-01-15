from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


class PubsubPublisher(Protocol):
    """
    Minimal Pub/Sub publisher interface.

    This is intentionally tiny so that unit tests and in-memory components can
    type against it without importing google-cloud-pubsub at import time.
    """

    def publish_json(
        self,
        *,
        topic: str,
        payload: Mapping[str, Any],
        attributes: Mapping[str, str] | None = None,
        timeout_s: float = 5.0,
    ) -> str: ...


@dataclass(frozen=True)
class NoopPubsubPublisher:
    """
    Safe default publisher that performs no network calls.
    """

    def publish_json(
        self,
        *,
        topic: str,
        payload: Mapping[str, Any],
        attributes: Mapping[str, str] | None = None,  # noqa: ARG002
        timeout_s: float = 5.0,  # noqa: ARG002
    ) -> str:
        _ = topic, payload
        return ""

