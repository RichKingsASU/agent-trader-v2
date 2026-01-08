from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from event_utils import choose_doc_id, ordering_ts, parse_ts
from firestore_writer import SourceInfo


def handle_market_bar_1m(
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
    Materialize 1m bar events into `market_bars_1m/{eventId|messageId}`.
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
    timeframe = payload.get("timeframe") if isinstance(payload.get("timeframe"), str) else None
    start = parse_ts(payload.get("start")) if "start" in payload else None
    end = parse_ts(payload.get("end")) if "end" in payload else None

    source = SourceInfo(topic=str(source_topic or ""), message_id=str(message_id), published_at=pubsub_published_at)
    applied, reason = firestore_writer.upsert_market_bar_1m(
        doc_id=doc_id,
        event_id=event_id,
        event_time=event_time,
        produced_at=produced_at,
        published_at=published_at,
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
        data=payload,
        source=source,
    )

    return {
        "kind": "market_bars_1m",
        "docId": doc_id,
        "symbol": symbol,
        "applied": bool(applied),
        "reason": str(reason),
        "eventTime": event_time.isoformat(),
    }

