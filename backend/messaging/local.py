from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Any, Deque, Dict, Iterable, Mapping, Optional

from backend.messaging.envelope import EventEnvelope


@dataclass(frozen=True, slots=True)
class _LocalTopicMessage:
    envelope: EventEnvelope


class InMemoryEventBus:
    """
    Minimal in-memory event bus for local testing/examples.

    This is NOT a production transport; it exists so developers can exercise the
    envelope + handler contract without requiring Pub/Sub at runtime.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._topics: Dict[str, Deque[_LocalTopicMessage]] = defaultdict(deque)

    def publish(
        self,
        *,
        topic: str,
        event_type: str,
        agent_name: str,
        payload: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
        git_sha: Optional[str] = None,
        ts: Optional[str] = None,
    ) -> EventEnvelope:
        env = EventEnvelope.new(
            event_type=event_type,
            agent_name=agent_name,
            payload=payload,
            trace_id=trace_id,
            git_sha=git_sha,
            ts=ts,
        )
        with self._lock:
            self._topics[str(topic)].append(_LocalTopicMessage(envelope=env))
        return env

    def drain(self, *, topic: str) -> Iterable[EventEnvelope]:
        with self._lock:
            q = self._topics[str(topic)]
            items = list(q)
            q.clear()
        return [m.envelope for m in items]

