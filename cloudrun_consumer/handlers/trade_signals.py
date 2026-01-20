from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from cloudrun_consumer.event_utils import choose_doc_id, ordering_ts, parse_ts
from cloudrun_consumer.firestore_writer import SourceInfo
from cloudrun_consumer.replay_support import ReplayContext, ensure_event_not_applied


def choose_trade_signal_dedupe_key(*, payload: dict[str, Any], message_id: str) -> str:
    """
    Deterministic replay dedupe key for trade_signals.

    Rules (in priority order):
    - payload.signal_id (preferred)
    - payload.eventId
    - Pub/Sub messageId (fallback)
    """
    if isinstance(payload, dict):
        for k in ("signal_id", "signalId"):
            v = payload.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        v = payload.get("eventId")
        if v is not None and str(v).strip():
            return str(v).strip()
    return str(message_id or "").strip()


def _extract_trade_signal_fields(
    *,
    payload: dict[str, Any],
    message_id: str,
    pubsub_published_at: datetime,
    source_topic: str,
) -> tuple[str, Optional[str], datetime, Optional[datetime], Optional[datetime], Optional[str], Optional[str], Optional[str], SourceInfo]:
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
    return (doc_id, event_id, event_time, produced_at, published_at, symbol, strategy, action, source)


def _handle_trade_signal_impl(
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

    doc_id, event_id, event_time, produced_at, published_at, symbol, strategy, action, source = _extract_trade_signal_fields(
        payload=payload,
        message_id=message_id,
        pubsub_published_at=pubsub_published_at,
        source_topic=source_topic,
    )
    replay_dedupe_key = choose_trade_signal_dedupe_key(payload=payload, message_id=message_id)
    applied, reason = firestore_writer.upsert_trade_signal(
        doc_id=doc_id,
        event_id=event_id,
        replay_dedupe_key=replay_dedupe_key,
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
    Replay-aware wrapper around `_handle_trade_signal_impl`.

    Note:
    - Pub/Sub messageId redelivery idempotency is enforced in `cloudrun_consumer.schema_router`.
    - When `replay` is provided, we additionally gate on a stable dedupe key (signal_id/eventId).
    """
    if replay is not None:
        doc_id, event_id, event_time, _produced_at, _published_at, symbol, _strategy, _action, _source = _extract_trade_signal_fields(
            payload=payload,
            message_id=message_id,
            pubsub_published_at=pubsub_published_at,
            source_topic=source_topic,
        )
        dedupe_key = choose_trade_signal_dedupe_key(payload=payload, message_id=message_id) or str(event_id or doc_id)
        try:
            db = getattr(firestore_writer, "_db")
            fs_mod = getattr(firestore_writer, "_firestore")

            def _txn(txn: Any) -> tuple[bool, str]:
                return ensure_event_not_applied(
                    txn=txn,
                    db=db,
                    replay=replay,
                    dedupe_key=dedupe_key,
                    event_time=event_time,
                    message_id=str(message_id),
                )

            txn = db.transaction()
            ok, why = fs_mod.transactional(_txn)(txn)
        except Exception:
            ok, why = True, "replay_idempotency_unavailable"

        if not ok:
            return {
                "kind": "trade_signals",
                "docId": str(doc_id),
                "symbol": symbol,
                "applied": False,
                "reason": str(why),
                "eventTime": event_time.isoformat(),
            }

    return _handle_trade_signal_impl(
        payload=payload,
        env=env,
        default_region=default_region,
        source_topic=source_topic,
        message_id=message_id,
        pubsub_published_at=pubsub_published_at,
        firestore_writer=firestore_writer,
        replay=replay,
    )

