from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from cloudrun_consumer.event_utils import choose_doc_id, ordering_ts, parse_ts
from cloudrun_consumer.firestore_writer import SourceInfo
from cloudrun_consumer.replay_support import ReplayContext


def handle_trade_signal(
    *,
    payload: dict[str, Any],
    env: str,
    default_region: str,
    source_topic: str,
    message_id: str,
    pubsub_published_at: datetime,
    firestore_writer: Any,
    replay: ReplayContext | None = None,
) -> dict[str, Any]:
    """
    Materialize trade signal events into `trade_signals/{eventId|messageId}`.
    """
    _ = env
    _ = default_region

    doc_id = choose_doc_id(payload=payload, message_id=message_id)
    event_id = None
    if "eventId" in payload and payload.get("eventId") is not None:
        event_id = str(payload.get("eventId")).strip() or None
    event_time = ordering_ts(payload=payload, pubsub_published_at=pubsub_published_at)

    produced_at = parse_ts(payload.get("producedAt")) if "producedAt" in payload else None
    published_at = parse_ts(payload.get("publishedAt")) if "publishedAt" in payload else None

    symbol = payload.get("symbol") if isinstance(payload.get("symbol"), str) else None
    strategy = payload.get("strategy") if isinstance(payload.get("strategy"), str) else None
    action = payload.get("action") if isinstance(payload.get("action"), str) else None

    source = SourceInfo(topic=str(source_topic or ""), message_id=str(message_id), published_at=pubsub_published_at)
    applied, reason = firestore_writer.upsert_trade_signal(
        doc_id=doc_id,
        event_id=event_id,
        event_time=event_time,
        produced_at=produced_at,
        published_at=published_at,
        symbol=symbol,
        strategy=strategy,
        action=action,
        data=payload,
        source=source,
        replay=replay,
    )

    return {
        "kind": "trade_signals",
        "docId": doc_id,
        "symbol": symbol,
        "applied": bool(applied),
        "reason": str(reason),
        "eventTime": event_time.isoformat(),
    }

