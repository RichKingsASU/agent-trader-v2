from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple

from cloudrun_consumer.event_utils import choose_doc_id, ordering_ts
from cloudrun_consumer.handlers.system_events import handle_system_event
from cloudrun_consumer.handlers.market_ticks import handle_market_tick
from cloudrun_consumer.handlers.market_bars_1m import handle_market_bar_1m
from cloudrun_consumer.handlers.trade_signals import handle_trade_signal
from cloudrun_consumer.handlers.ingest_pipelines import handle_ingest_pipeline
from cloudrun_consumer.idempotency import ensure_message_once


@dataclass(frozen=True)
class RoutedHandler:
    name: str
    handler: Callable[..., dict[str, Any]]


def _wrap_trade_signals(handler: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """
    Guard trade_signals against Pub/Sub redelivery re-execution.

    Enforces `ensure_message_once(messageId)` *before* calling the underlying handler.
    """

    def _wrapped(**kwargs: Any) -> dict[str, Any]:
        payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
        message_id = str(kwargs.get("message_id") or "").strip()

        if message_id:
            firestore_writer = kwargs.get("firestore_writer")
            try:
                db = getattr(firestore_writer, "_db")
                fs_mod = getattr(firestore_writer, "_firestore")
                col_fn = getattr(firestore_writer, "_col", None)
                col_name = col_fn("ops_pubsub_dedupe") if callable(col_fn) else "ops_pubsub_dedupe"

                # Firestore doc ids cannot contain '/', and very long ids are inconvenient.
                mid_doc_id = message_id.replace("/", "_")[:256]
                dedupe_ref = db.collection(col_name).document(mid_doc_id)

                def _txn(txn: Any) -> bool:
                    first, _existing = ensure_message_once(
                        txn=txn,
                        dedupe_ref=dedupe_ref,
                        message_id=message_id,
                        doc={
                            "kind": "trade_signals",
                            "topic": str(kwargs.get("source_topic") or ""),
                            "handler": "trade_signals",
                        },
                    )
                    return bool(first)

                txn = db.transaction()
                first_time = bool(fs_mod.transactional(_txn)(txn))
                if not first_time:
                    pubsub_published_at = kwargs.get("pubsub_published_at")
                    event_time = ordering_ts(payload=payload, pubsub_published_at=pubsub_published_at)
                    doc_id = choose_doc_id(payload=payload, message_id=message_id)
                    symbol = payload.get("symbol") if isinstance(payload.get("symbol"), str) else None
                    return {
                        "kind": "trade_signals",
                        "docId": doc_id,
                        "symbol": symbol,
                        "applied": False,
                        "reason": "duplicate_message_noop",
                        "eventTime": event_time.isoformat(),
                    }
            except Exception:
                # Fail-open: if Firestore client wiring is unavailable, do not block processing.
                pass

        return handler(**kwargs)

    return _wrapped


def route_payload(
    *,
    payload: dict[str, Any],
    attributes: dict[str, str],
    topic: Optional[str] = None,
) -> Optional[RoutedHandler]:
    """
    Phase 1 router: system events -> ops_services.

    This intentionally does NOT modify producers. We route based on shape:
    `service` + `timestamp` indicates a system event record.
    """
    _ = attributes  # reserved for future schemaVersion routing
    if isinstance(payload.get("service"), str) and payload.get("service"):
        if payload.get("timestamp") is not None:
            return RoutedHandler(name="system_events", handler=handle_system_event)

    # Topic-based routing for additional streams.
    t = (topic or "").strip()
    if t == "market-ticks":
        return RoutedHandler(name="market_ticks", handler=handle_market_tick)
    if t == "market-bars-1m":
        return RoutedHandler(name="market_bars_1m", handler=handle_market_bar_1m)
    if t == "trade-signals":
        return RoutedHandler(name="trade_signals", handler=_wrap_trade_signals(handle_trade_signal))
    if t in {"ingest-heartbeat", "ingest-pipelines", "ingest-pipeline-health"}:
        return RoutedHandler(name="ingest_pipelines", handler=handle_ingest_pipeline)
    return None

