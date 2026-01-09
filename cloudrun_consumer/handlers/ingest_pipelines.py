from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from cloudrun_consumer.event_utils import as_utc, parse_ts
from cloudrun_consumer.firestore_writer import SourceInfo


def _first_str(payload: dict[str, Any], keys: list[str]) -> Optional[str]:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _first_num(payload: dict[str, Any], keys: list[str]) -> Optional[float]:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def handle_ingest_pipeline(
    *,
    payload: dict[str, Any],
    env: str,
    default_region: str,
    source_topic: str,
    message_id: str,
    pubsub_published_at: datetime,
    firestore_writer: Any,
) -> dict[str, Any]:
    """
    Materialize ingest/pipeline health events into `ingest_pipelines/{pipelineId}`.

    Hardening goals:
    - deterministic doc id (`pipelineId`)
    - last-write-wins using Pub/Sub `publishTime` (stored as `published_at`)
    - protection against out-of-order delivery
    - store `source.message_id` for dedupe visibility
    """
    _ = default_region

    pipeline_id = _first_str(
        payload,
        keys=[
            "pipeline_id",
            "pipelineId",
            "pipeline",
            "pipelineName",
            "ingestPipeline",
            "name",
        ],
    )
    if not pipeline_id:
        raise ValueError("missing_pipeline_id")
    # Firestore doc IDs cannot include '/', sanitize minimally.
    pipeline_id = pipeline_id.replace("/", "_")

    status = _first_str(payload, keys=["status", "state", "health"]) or "UNKNOWN"

    lag_seconds = _first_num(payload, keys=["lag_seconds", "lagSeconds", "lag"])
    throughput_per_min = _first_num(payload, keys=["throughput_per_min", "throughputPerMin", "throughput", "events_per_min"])
    error_rate_per_min = _first_num(payload, keys=["error_rate_per_min", "errorRatePerMin", "error_rate"])

    # Best-effort event timestamp for display/debug; ordering is enforced by published_at.
    last_event_at = (
        parse_ts(payload.get("last_event_at"))
        or parse_ts(payload.get("lastEventAt"))
        or parse_ts(payload.get("last_seen_at"))
        or parse_ts(payload.get("lastSeenAt"))
        or parse_ts(payload.get("eventTime"))
        or parse_ts(payload.get("timestamp"))
        or parse_ts(payload.get("ts"))
        or parse_ts(payload.get("time"))
        or as_utc(pubsub_published_at)
    )

    source = SourceInfo(topic=str(source_topic or ""), message_id=str(message_id), published_at=as_utc(pubsub_published_at))
    applied, reason = firestore_writer.dedupe_and_upsert_ingest_pipeline(
        message_id=str(message_id),
        pipeline_id=str(pipeline_id),
        source=source,
        fields={
            # Include env without forcing a schema change; low-cardinality.
            "environment": str(env or "unknown"),
            "name": str(payload.get("name")).strip() if isinstance(payload.get("name"), str) and payload.get("name").strip() else str(pipeline_id),
            "status": str(status),
            "lag_seconds": lag_seconds,
            "throughput_per_min": throughput_per_min,
            "error_rate_per_min": error_rate_per_min,
            "last_event_at": last_event_at,
        },
    )

    return {
        "kind": "ingest_pipelines",
        "pipelineId": str(pipeline_id),
        "applied": bool(applied),
        "reason": str(reason),
        "publishedAt": as_utc(pubsub_published_at).isoformat(),
    }

