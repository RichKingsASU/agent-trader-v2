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
    Materializes ingest/pipeline health events into ingest_pipelines.
    """
    writer = FirestoreWriter()

    pipeline = _first_str(
        payload,
        keys=[
            "pipeline",
            "pipelineName",
            "pipeline_id",
            "ingestPipeline",
            "name",
        ],
    )
    if not pipeline:
        return

    pipeline_id = _normalize_id(pipeline)

    state = _first_str(payload, keys=["state", "status", "health"]) or "UNKNOWN"
    lag_seconds = payload.get("lagSeconds") if isinstance(payload.get("lagSeconds"), (int, float)) else None
    last_success_at = _first_str(payload, keys=["lastSuccessAt", "last_success_at"])

    fields: Dict[str, Any] = {
        "pipelineId": pipeline_id,
        "pipeline": pipeline,
        "state": state,
        "lagSeconds": lag_seconds,
        "lastSuccessAt": last_success_at,
        "lastEventType": ctx.event_type,
        "lastEvent": {
            "eventType": ctx.event_type,
        },
    }
    fields = {k: v for k, v in fields.items() if v is not None}

    source = SourceContext(
        message_id=ctx.message_id,
        published_at=_published_at_from_iso(ctx.published_at_iso),
        topic=ctx.topic,
    )
    writer.upsert_ingest_pipeline(pipeline_id=pipeline_id, source=source, fields=fields)


def _published_at_from_iso(iso: str) -> datetime:
    from datetime import timezone

    if not iso:
        return datetime.now(timezone.utc)
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

