from __future__ import annotations

import base64
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_rfc3339_best_effort(value: Any) -> Optional[datetime]:
    """
    Parse Pub/Sub publishTime (RFC3339-ish) into a timezone-aware UTC datetime.

    Examples seen in the wild:
    - 2026-01-08T12:34:56.123Z
    - 2026-01-08T12:34:56Z
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Python wants +00:00 instead of Z.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _json_loads_best_effort(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        try:
            # Sometimes Pub/Sub publishes plain text; keep it human-readable.
            return {"_raw": raw.decode("utf-8", errors="replace")}
        except Exception:
            return {"_raw_b64": base64.b64encode(raw).decode("ascii")}


def extract_event_type(payload: Any, attributes: dict[str, str]) -> str:
    """
    Best-effort extraction of an event type label.

    Preference order:
    - message attributes: event_type / eventType / type
    - JSON payload: event_type / eventType / type
    """
    for k in ("event_type", "eventType", "type"):
        v = attributes.get(k)
        if v:
            return str(v).strip() or "unknown"

    if isinstance(payload, dict):
        for k in ("event_type", "eventType", "type"):
            v = payload.get(k)
            if v:
                return str(v).strip() or "unknown"

    return "unknown"


@dataclass(frozen=True, slots=True)
class IngestedEvent:
    event_id: str
    event_type: str
    received_at_utc: datetime
    publish_time_utc: Optional[datetime]
    message_id: Optional[str]
    subscription: Optional[str]
    attributes: dict[str, str]
    payload: Any


@dataclass(frozen=True, slots=True)
class EventSummary:
    message_count: int
    last_event_time_utc: Optional[datetime]
    latest_payload_by_event_type: dict[str, Any]


def parse_pubsub_push(body: dict[str, Any]) -> IngestedEvent:
    """
    Parse a Pub/Sub push payload (Cloud Run / HTTP push subscription format).

    Expected shape:
      { "message": { "data": "base64...", "attributes": {...}, "messageId": "...", "publishTime": "..." },
        "subscription": "projects/.../subscriptions/..." }
    """
    if not isinstance(body, dict):
        raise ValueError("invalid body (not object)")

    subscription = body.get("subscription")
    if not isinstance(subscription, str) or not subscription.strip():
        raise ValueError("missing subscription")

    msg = body.get("message")
    if not isinstance(msg, dict):
        raise ValueError("missing message")

    message_id = msg.get("messageId") or msg.get("message_id") or None
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("missing message.messageId")

    publish_time_raw = msg.get("publishTime") or msg.get("publish_time")
    if not isinstance(publish_time_raw, str) or not publish_time_raw.strip():
        raise ValueError("missing message.publishTime")

    data_b64 = msg.get("data")
    if not isinstance(data_b64, str) or not data_b64.strip():
        raise ValueError("missing message.data")

    try:
        raw = base64.b64decode(data_b64.encode("ascii"), validate=True)
    except Exception as e:
        raise ValueError("invalid message.data (base64)") from e
    payload = _json_loads_best_effort(raw)

    attrs = msg.get("attributes") if isinstance(msg.get("attributes"), dict) else {}
    attributes = {str(k): str(v) for k, v in (attrs or {}).items()}

    event_type = extract_event_type(payload, attributes)

    publish_time_utc = _parse_rfc3339_best_effort(publish_time_raw)

    # Prefer Pub/Sub messageId for idempotency.
    event_id = str(message_id).strip() if message_id else uuid.uuid4().hex

    return IngestedEvent(
        event_id=event_id,
        event_type=event_type,
        received_at_utc=_utcnow(),
        publish_time_utc=publish_time_utc,
        message_id=str(message_id).strip() if message_id else None,
        subscription=str(subscription).strip(),
        attributes=attributes,
        payload=payload,
    )


class EventStore:
    def write_event(self, ev: IngestedEvent) -> None:  # pragma: no cover (interface)
        raise NotImplementedError

    def get_summary(self) -> EventSummary:  # pragma: no cover (interface)
        raise NotImplementedError


class InMemoryEventStore(EventStore):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count = 0
        self._last: Optional[datetime] = None
        self._latest_by_type: dict[str, Any] = {}

    def write_event(self, ev: IngestedEvent) -> None:
        with self._lock:
            self._count += 1
            self._last = ev.received_at_utc
            self._latest_by_type[ev.event_type] = ev.payload

    def get_summary(self) -> EventSummary:
        with self._lock:
            return EventSummary(
                message_count=int(self._count),
                last_event_time_utc=self._last,
                latest_payload_by_event_type=dict(self._latest_by_type),
            )


class FirestoreEventStore(EventStore):
    """
    Firestore-backed store optimized for visibility.

    Writes:
    - One event document per message (for audit/debug).
    - One summary document containing counters + latest payload per event type.
    """

    def __init__(
        self,
        *,
        project_id: Optional[str] = None,
        events_collection: str = "pubsub_events",
        summary_collection: str = "ops",
        summary_doc_id: str = "pubsub_event_ingestion",
    ) -> None:
        # Lazy import so in-memory / minimal envs can still import this module.
        from backend.persistence.firebase_client import get_firestore_client

        self._db = get_firestore_client(project_id=project_id)
        self._events_collection = str(events_collection)
        self._summary_collection = str(summary_collection)
        self._summary_doc_id = str(summary_doc_id)

        # Late import so non-Firestore runs (tests/local) can still import modules.
        from firebase_admin import firestore as admin_firestore  # type: ignore

        self._FieldValue = admin_firestore.FieldValue

    def write_event(self, ev: IngestedEvent) -> None:
        # Event record (best-effort; idempotent on message_id).
        event_doc = {
            "event_type": ev.event_type,
            "received_at": ev.received_at_utc,
            "publish_time": ev.publish_time_utc,
            "message_id": ev.message_id,
            "subscription": ev.subscription,
            "attributes": ev.attributes,
            "payload": ev.payload,
        }
        self._db.collection(self._events_collection).document(ev.event_id).set(event_doc, merge=True)

        # Summary doc (fast path for UI reads).
        summary_ref = self._db.collection(self._summary_collection).document(self._summary_doc_id)
        summary_ref.set(
            {
                "message_count": self._FieldValue.increment(1),
                "last_event_time": self._FieldValue.serverTimestamp(),
                "last_event_type": ev.event_type,
                "last_message_id": ev.message_id,
                "last_subscription": ev.subscription,
                "last_publish_time": ev.publish_time_utc,
                # Store the latest payload per type under a map keyed by event_type.
                f"latest_payload_by_event_type.{ev.event_type}": ev.payload,
            },
            merge=True,
        )

    def get_summary(self) -> EventSummary:
        snap = self._db.collection(self._summary_collection).document(self._summary_doc_id).get()
        d = snap.to_dict() if snap.exists else {}
        latest = d.get("latest_payload_by_event_type") if isinstance(d, dict) else None
        if not isinstance(latest, dict):
            latest = {}
        return EventSummary(
            message_count=int((d or {}).get("message_count") or 0),
            last_event_time_utc=(d or {}).get("last_event_time"),
            latest_payload_by_event_type=dict(latest),
        )


def build_event_store() -> EventStore:
    """
    Factory:
    - EVENT_STORE=memory forces in-memory.
    - default attempts Firestore, falls back to memory if init fails.
    """
    mode = (os.getenv("EVENT_STORE") or "").strip().lower()
    if mode in {"mem", "memory", "inmemory", "in-memory"}:
        return InMemoryEventStore()

    project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None
    try:
        return FirestoreEventStore(project_id=project_id)
    except Exception:
        # Visibility-first fallback for dev / misconfigured ADC.
        return InMemoryEventStore()

