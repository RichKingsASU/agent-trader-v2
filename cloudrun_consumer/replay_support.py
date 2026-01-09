from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Tuple

from cloudrun_consumer.idempotency import ensure_doc_once


APPLIED_EVENTS_COLLECTION = "ops_applied_events"
REPLAY_MARKERS_COLLECTION = "ops_replay_markers"
REPLAY_RUNS_COLLECTION = "ops_replay_runs"


@dataclass(frozen=True)
class ReplayContext:
    """
    Minimal replay context.

    If `run_id` is set, the consumer is considered to be operating in "replay mode"
    and may perform additional bookkeeping (markers + applied-event checks).
    """

    run_id: str
    consumer: str
    topic: str


def applied_event_doc_id(*, consumer: str, topic: str, dedupe_key: str) -> str:
    # Keep ids readable + deterministic; Firestore id limits are generous.
    # If callers pass long dedupe keys, they should normalize upstream.
    return f"{consumer}__{topic}__{dedupe_key}"


def ensure_event_not_applied(
    *,
    txn: Any,
    db: Any,
    replay: ReplayContext,
    dedupe_key: str,
    event_time: datetime,
    message_id: str,
    expire_at: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """
    Replay-mode idempotency: skip events already applied in this Firestore DB.

    Implementation:
    - Checks/creates `ops_applied_events/{consumer__topic__dedupeKey}` transactionally.
    - Only safe if `dedupe_key` is stable across replays (prefer producer eventId).
    """
    key = str(dedupe_key or "").strip()
    if not key:
        return True, "no_dedupe_key"

    ref = db.collection(APPLIED_EVENTS_COLLECTION).document(applied_event_doc_id(consumer=replay.consumer, topic=replay.topic, dedupe_key=key))
    first_time, _ = ensure_doc_once(
        txn=txn,
        dedupe_ref=ref,
        key=key,
        doc={
            # Prefer a real timestamp over relying on SERVER_TIMESTAMP availability.
            "createdAt": event_time,
            "consumer": str(replay.consumer),
            "topic": str(replay.topic),
            "dedupeKey": str(key),
            "replayRunId": str(replay.run_id),
            "eventTime": event_time,
            "messageId": str(message_id),
            # Optional: set this and configure Firestore TTL on it.
            **({"expireAt": expire_at} if expire_at is not None else {}),
        },
    )
    return (True, "not_applied_yet") if first_time else (False, "already_applied_noop")


def write_replay_marker(
    *,
    db: Any,
    replay: ReplayContext,
    message_id: str,
    pubsub_published_at: datetime,
    event_time: datetime,
    handler: str,
    applied: bool,
    reason: str,
) -> None:
    """
    Best-effort progress markers to Firestore:
    - `ops_replay_runs/{runId}`: run presence + lastUpdatedAt
    - `ops_replay_markers/{consumer__topic}`: lastSeen / lastApplied watermarks
    """
    # Avoid relying on SERVER_TIMESTAMP on the client object; store explicit times.
    updated_at = pubsub_published_at

    run_ref = db.collection(REPLAY_RUNS_COLLECTION).document(str(replay.run_id))
    run_ref.set(
        {
            "runId": str(replay.run_id),
            "consumer": str(replay.consumer),
            "lastUpdatedAt": updated_at,
            # Map-of-topics avoids arrayUnion dependency.
            f"topics.{replay.topic}": True,
        },
        merge=True,
    )

    marker_ref = db.collection(REPLAY_MARKERS_COLLECTION).document(f"{replay.consumer}__{replay.topic}")
    update: dict[str, Any] = {
        "consumer": str(replay.consumer),
        "topic": str(replay.topic),
        "replayRunId": str(replay.run_id),
        "updatedAt": updated_at,
        "lastSeen": {
            "messageId": str(message_id),
            "publishedAt": pubsub_published_at,
            "eventTime": event_time,
            "handler": str(handler),
            "applied": bool(applied),
            "reason": str(reason),
        },
    }
    if applied:
        update["lastApplied"] = {
            "messageId": str(message_id),
            "publishedAt": pubsub_published_at,
            "eventTime": event_time,
            "handler": str(handler),
            "reason": str(reason),
        }
    marker_ref.set(update, merge=True)

