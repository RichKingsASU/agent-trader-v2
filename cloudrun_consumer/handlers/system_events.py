from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional

from firestore_writer import FirestoreWriter, SourceContext
from schema_router import EventContext


_ID_SAFE_RE = re.compile(r"[^a-z0-9_\-]+")


def _normalize_id(value: str) -> str:
    v = (value or "").strip().lower()
    v = v.replace(" ", "-")
    v = _ID_SAFE_RE.sub("-", v)
    v = re.sub(r"-{2,}", "-", v).strip("-")
    return v or "unknown"


def _first_str(payload: Dict[str, Any], keys: list[str]) -> Optional[str]:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def handle(payload: Dict[str, Any], ctx: EventContext) -> None:
    """
    Materializes system/service-related events into ops_services.
    """
    writer = FirestoreWriter()

    service = _first_str(
        payload,
        keys=[
            "service",
            "serviceName",
            "service_id",
            "component",
            "app",
            "name",
        ],
    )
    if not service:
        # Nothing to materialize.
        return

    service_id = _normalize_id(service)

    status = _first_str(payload, keys=["status", "state", "health", "level"]) or "UNKNOWN"
    severity = _first_str(payload, keys=["severity", "priority"]) or "INFO"
    message = _first_str(payload, keys=["message", "detail", "reason", "summary"])

    # Keep small derived fields + raw lastEvent for debugging.
    fields: Dict[str, Any] = {
        "serviceId": service_id,
        "service": service,
        "status": status,
        "severity": severity,
        "lastEventType": ctx.event_type,
        "lastPublishedAt": payload.get("publishedAt") if isinstance(payload.get("publishedAt"), str) else None,
        "lastEvent": {
            "eventType": ctx.event_type,
            "message": message,
        },
    }

    # Drop Nones to avoid cluttering docs.
    fields = {k: v for k, v in fields.items() if v is not None}

    source = SourceContext(
        message_id=ctx.message_id,
        published_at=_published_at_from_iso(ctx.published_at_iso),
        topic=ctx.topic,
    )
    writer.upsert_ops_service(service_id=service_id, source=source, fields=fields)


def _published_at_from_iso(iso: str) -> datetime:
    # Guaranteed non-empty by main, but be defensive.
    from datetime import timezone

    if not iso:
        return datetime.now(timezone.utc)
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

