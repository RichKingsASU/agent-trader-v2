from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_rfc3339(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class IngestedEvent:
    event_id: str
    message_id: str
    event_type: str
    payload: Any
    attributes: dict[str, str] = field(default_factory=dict)
    publish_time_utc: Optional[datetime] = None
    received_at_utc: datetime = field(default_factory=_utc_now)
    subscription: Optional[str] = None


def parse_pubsub_push(body: Mapping[str, Any]) -> IngestedEvent:
    """
    Parse a Pub/Sub push body into an `IngestedEvent`.

    Constraints:
    - Pure / deterministic: no GCP dependencies; safe for unit tests.
    - Raises ValueError on malformed envelopes.
    """
    if not isinstance(body, Mapping):
        raise ValueError("invalid_envelope")
    message = body.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("missing_message")

    message_id = str(message.get("messageId") or "").strip()
    if not message_id:
        raise ValueError("missing messageId")

    attrs_raw = message.get("attributes") or {}
    attributes: dict[str, str] = {}
    if isinstance(attrs_raw, Mapping):
        for k, v in attrs_raw.items():
            if k is None:
                continue
            attributes[str(k)] = "" if v is None else str(v)

    data_b64 = message.get("data")
    if not isinstance(data_b64, str) or not data_b64.strip():
        raise ValueError("missing data")
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception as e:
        raise ValueError("invalid base64 data") from e
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ValueError("invalid json payload") from e

    event_type = str(attributes.get("event_type") or "").strip()
    if not event_type and isinstance(decoded, dict):
        event_type = str(decoded.get("event_type") or decoded.get("eventType") or "").strip()
    event_type = event_type or "unknown"

    publish_time = _parse_rfc3339(message.get("publishTime"))
    subscription = str(body.get("subscription") or "").strip() or None

    return IngestedEvent(
        event_id=message_id,
        message_id=message_id,
        event_type=event_type,
        payload=decoded,
        attributes=attributes,
        publish_time_utc=publish_time,
        received_at_utc=_utc_now(),
        subscription=subscription,
    )


@dataclass(frozen=True, slots=True)
class EventStoreSummary:
    message_count: int
    latest_payload_by_event_type: dict[str, Any]


class InMemoryEventStore:
    """
    Deterministic, process-local event store used by unit tests.
    """

    def __init__(self) -> None:
        self._events: list[IngestedEvent] = []
        self._latest_by_type: dict[str, Any] = {}

    def write_event(self, ev: IngestedEvent) -> None:
        self._events.append(ev)
        self._latest_by_type[str(ev.event_type)] = ev.payload

    def get_summary(self) -> EventStoreSummary:
        return EventStoreSummary(message_count=len(self._events), latest_payload_by_event_type=dict(self._latest_by_type))