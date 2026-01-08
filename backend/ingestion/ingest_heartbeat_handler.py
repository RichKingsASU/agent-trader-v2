from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from backend.ingestion.pubsub_event_store import IngestedEvent
from backend.time.utc_audit import ensure_utc


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt_best_effort(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, source="backend.ingestion.ingest_heartbeat_handler._parse_dt_best_effort", field="datetime")
    try:
        # Keep dependency-local: this repo already has a tolerant time parser.
        from backend.time.nyse_time import parse_ts

        dt = parse_ts(value)
        return ensure_utc(dt, source="backend.ingestion.ingest_heartbeat_handler._parse_dt_best_effort", field="parsed")
    except Exception:
        return None


def extract_subscription_id(subscription: Optional[str]) -> Optional[str]:
    """
    Extracts the subscription id from:
      projects/<p>/subscriptions/<id>
    """
    if not subscription:
        return None
    s = str(subscription).strip()
    if not s:
        return None
    parts = [p for p in s.split("/") if p]
    if len(parts) >= 4 and parts[-2] == "subscriptions":
        return parts[-1]
    return parts[-1] if parts else None


@dataclass(frozen=True, slots=True)
class IngestHeartbeat:
    """
    Canonical heartbeat record derived from a Pub/Sub push event.
    """

    pipeline_id: str
    status: str
    event_ts_utc: datetime
    tenant_id: Optional[str]
    agent_name: Optional[str]
    git_sha: Optional[str]
    trace_id: Optional[str]
    raw_payload: Any


def _unwrap_envelope(payload: Any) -> tuple[Optional[Mapping[str, Any]], Any]:
    """
    If payload looks like an EventEnvelope dict, return (envelope, envelope["payload"]).
    Otherwise return (None, payload).
    """
    if not isinstance(payload, dict):
        return None, payload
    # Minimal required keys for EventEnvelope.
    if {"event_type", "agent_name", "git_sha", "ts", "payload", "trace_id"}.issubset(payload.keys()):
        return payload, payload.get("payload")
    return None, payload


def parse_ingest_heartbeat(ev: IngestedEvent) -> Optional[IngestHeartbeat]:
    """
    Expected event payload for the ingest-heartbeat topic:

    Preferred: EventEnvelope JSON in Pub/Sub message data:
      {
        "event_type": "ingest.heartbeat",
        "agent_name": "<pipeline_id or producer name>",
        "git_sha": "<sha>",
        "ts": "2026-01-08T12:34:56.123Z",
        "payload": {
          "pipeline_id": "<pipeline_id>",   # optional if agent_name is the id
          "tenant_id": "<tenant>",          # optional
          "status": "running"               # required-ish
        },
        "trace_id": "<id>"
      }

    Also accepted (back-compat): message data is the inner payload object directly.
    """
    envelope, inner = _unwrap_envelope(ev.payload)

    # Determine pipeline id.
    pipeline_id = None
    tenant_id = None
    status = None
    inner_ts = None

    if isinstance(inner, dict):
        pipeline_id = inner.get("pipeline_id") or inner.get("pipeline") or inner.get("service")
        tenant_id = inner.get("tenant_id") or inner.get("tenant")
        status = inner.get("status")
        inner_ts = inner.get("ts") or inner.get("timestamp")

    agent_name = str(envelope.get("agent_name")) if isinstance(envelope, dict) and envelope.get("agent_name") else None
    git_sha = str(envelope.get("git_sha")) if isinstance(envelope, dict) and envelope.get("git_sha") else None
    trace_id = str(envelope.get("trace_id")) if isinstance(envelope, dict) and envelope.get("trace_id") else None

    pipeline_id = str(pipeline_id or agent_name or "").strip() or None
    if not pipeline_id:
        return None

    status_s = str(status or "").strip() or "unknown"

    # Pick the best timestamp available, in priority order:
    # - envelope.ts (producer ts)
    # - inner.ts (payload ts)
    # - Pub/Sub publishTime
    # - receive time
    env_ts = envelope.get("ts") if isinstance(envelope, dict) else None
    event_ts = _parse_dt_best_effort(env_ts) or _parse_dt_best_effort(inner_ts) or ev.publish_time_utc or ev.received_at_utc
    event_ts = ensure_utc(event_ts, source="backend.ingestion.ingest_heartbeat_handler.parse_ingest_heartbeat", field="event_ts")

    tenant_id_s = str(tenant_id).strip() if tenant_id is not None else None
    tenant_id_s = tenant_id_s or None

    return IngestHeartbeat(
        pipeline_id=pipeline_id,
        status=status_s,
        event_ts_utc=event_ts,
        tenant_id=tenant_id_s,
        agent_name=agent_name,
        git_sha=git_sha,
        trace_id=trace_id,
        raw_payload=ev.payload,
    )


@dataclass(frozen=True, slots=True)
class ApplyResult:
    outcome: str  # "applied" | "duplicate" | "stale_rejected" | "error"
    pipeline_doc_path: str
    dedupe_doc_path: str
    reason: Optional[str] = None


def apply_ingest_heartbeat_to_firestore(
    *,
    hb: IngestHeartbeat,
    pubsub_message_id: str,
    pubsub_publish_time_utc: Optional[datetime],
    project_id: Optional[str] = None,
) -> ApplyResult:
    """
    Firestore write logic (single topic only):
    - Target doc: ingest_pipelines/{pipeline_id}
    - Dedupe doc: ingest_pipelines_dedupe/{pubsub_message_id}

    Guarantees:
    - Idempotent: retries/redeliveries of the same Pub/Sub message_id are no-ops.
    - Stale rejection: if hb.event_ts_utc < current last_event_ts, we do NOT update the pipeline doc.
    """
    if not pubsub_message_id:
        raise ValueError("pubsub_message_id is required for idempotency")

    from backend.persistence.firebase_client import get_firestore_client
    from firebase_admin import firestore as admin_firestore  # type: ignore

    db = get_firestore_client(project_id=project_id)
    pipeline_ref = db.collection("ingest_pipelines").document(str(hb.pipeline_id))
    dedupe_ref = db.collection("ingest_pipelines_dedupe").document(str(pubsub_message_id))

    pipeline_path = f"ingest_pipelines/{hb.pipeline_id}"
    dedupe_path = f"ingest_pipelines_dedupe/{pubsub_message_id}"

    transaction = db.transaction()

    @admin_firestore.transactional
    def _txn(txn):  # type: ignore[no-untyped-def]
        dedupe_snap = dedupe_ref.get(transaction=txn)
        if getattr(dedupe_snap, "exists", False):
            return ApplyResult(outcome="duplicate", pipeline_doc_path=pipeline_path, dedupe_doc_path=dedupe_path)

        pipe_snap = pipeline_ref.get(transaction=txn)
        pipe = pipe_snap.to_dict() if getattr(pipe_snap, "exists", False) else {}
        last_ts = _parse_dt_best_effort((pipe or {}).get("last_event_ts") or (pipe or {}).get("last_heartbeat_at"))

        if last_ts is not None and hb.event_ts_utc < last_ts:
            txn.set(
                dedupe_ref,
                {
                    "pipeline_id": hb.pipeline_id,
                    "seen_at": admin_firestore.SERVER_TIMESTAMP,
                    "event_ts": hb.event_ts_utc,
                    "publish_time": pubsub_publish_time_utc,
                    "outcome": "stale_rejected",
                    "reason": "event_ts_older_than_last_event_ts",
                },
                merge=True,
            )
            return ApplyResult(
                outcome="stale_rejected",
                pipeline_doc_path=pipeline_path,
                dedupe_doc_path=dedupe_path,
                reason="event_ts_older_than_last_event_ts",
            )

        # Apply update (merge).
        txn.set(
            pipeline_ref,
            {
                "pipeline_id": hb.pipeline_id,
                "tenant_id": hb.tenant_id,
                "status": hb.status,
                "last_event_ts": hb.event_ts_utc,
                "last_pubsub_message_id": pubsub_message_id,
                "last_pubsub_publish_time": pubsub_publish_time_utc,
                "last_trace_id": hb.trace_id,
                "last_agent_name": hb.agent_name,
                "last_git_sha": hb.git_sha,
                "updated_at": admin_firestore.SERVER_TIMESTAMP,
                # Keep the last raw payload for debugging this slice.
                "last_payload": hb.raw_payload,
            },
            merge=True,
        )
        txn.set(
            dedupe_ref,
            {
                "pipeline_id": hb.pipeline_id,
                "seen_at": admin_firestore.SERVER_TIMESTAMP,
                "event_ts": hb.event_ts_utc,
                "publish_time": pubsub_publish_time_utc,
                "outcome": "applied",
            },
            merge=True,
        )
        return ApplyResult(outcome="applied", pipeline_doc_path=pipeline_path, dedupe_doc_path=dedupe_path)

    return _txn(transaction)

