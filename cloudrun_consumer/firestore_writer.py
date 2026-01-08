from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Tuple

from time_audit import ensure_utc

from idempotency import ensure_message_once
from replay_support import ReplayContext, ensure_event_not_applied
from time_audit import ensure_utc


def _lww_key(*, published_at: datetime, message_id: str) -> tuple[float, str]:
    """
    Last-write-wins ordering key for Pub/Sub-derived writes.

    Ordering:
    - primary: published_at (UTC)
    - tie-break: message_id lexicographic (stable)
    """
    pub = ensure_utc(published_at, source="cloudrun_consumer.firestore_writer._lww_key", field="published_at")
    return (pub.timestamp(), str(message_id or ""))


def _existing_pubsub_lww(existing: dict[str, Any]) -> tuple[Optional[datetime], Optional[str]]:
    """
    Best-effort extractor for existing Pub/Sub ordering fields across historical shapes.

    Returns: (published_at_utc, message_id)
    """
    if not isinstance(existing, dict):
        return None, None

    pub: Optional[datetime] = None
    mid: Optional[str] = None

    # snake_case
    v = existing.get("published_at")
    if isinstance(v, datetime):
        pub = ensure_utc(v, source="cloudrun_consumer.firestore_writer._existing_pubsub_lww", field="published_at")

    src = existing.get("source")
    if isinstance(src, dict):
        mid_v = src.get("message_id")
        if mid_v is not None and str(mid_v).strip():
            mid = str(mid_v).strip()

        # camelCase
        if pub is None:
            pv = src.get("publishedAt")
            if isinstance(pv, str) and pv.strip():
                s = pv.strip()
                if s.endswith("Z"):
                    s = s[:-1] + "+00:00"
                try:
                    pub = ensure_utc(datetime.fromisoformat(s), source="cloudrun_consumer.firestore_writer._existing_pubsub_lww", field="publishedAt")
                except Exception:
                    pub = None
        if mid is None:
            mv = src.get("messageId")
            if mv is not None and str(mv).strip():
                mid = str(mv).strip()

    return pub, mid


def _as_utc(dt: datetime) -> datetime:
    return ensure_utc(dt, source="cloudrun_consumer.firestore_writer._as_utc", field="dt")


def _parse_rfc3339(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, source="cloudrun_consumer.firestore_writer._parse_rfc3339", field="datetime")
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return ensure_utc(dt, source="cloudrun_consumer.firestore_writer._parse_rfc3339", field="iso_string")
    except Exception:
        return None


def _short_hash_id(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _max_dt(*values: Optional[datetime]) -> Optional[datetime]:
    xs = [v for v in values if isinstance(v, datetime)]
    if not xs:
        return None
    return max(_as_utc(v) for v in xs)


def _lww_key(*, published_at: datetime, message_id: str) -> tuple[datetime, str]:
    """
    Last-write-wins ordering key: publishedAt first, then messageId.
    """
    return (_as_utc(published_at), str(message_id or ""))


def _existing_pubsub_lww(existing: Any) -> tuple[Optional[datetime], Optional[str]]:
    """
    Extract a best-effort (published_at, message_id) from existing Firestore doc shapes.
    """
    if not isinstance(existing, dict):
        return None, None
    pub = _parse_rfc3339(existing.get("published_at")) or _parse_rfc3339(existing.get("publishedAt"))
    src = existing.get("source")
    if isinstance(src, dict):
        pub = pub or _parse_rfc3339(src.get("published_at")) or _parse_rfc3339(src.get("publishedAt"))
        mid = src.get("message_id") or src.get("messageId")
    else:
        mid = existing.get("message_id") or existing.get("messageId")
    mid_s = str(mid).strip() if mid is not None else ""
    return pub, (mid_s or None)


OPS_SERVICE_STATUSES = ("healthy", "degraded", "down", "unknown", "maintenance")


def _normalize_ops_service_status(raw: Any) -> tuple[str, str]:
    raw_s = "" if raw is None else str(raw)
    s = raw_s.strip().lower()
    if not s:
        return "unknown", raw_s
    if s in {"ok", "okay", "healthy", "running", "up", "online", "alive", "serving", "ready"}:
        return "healthy", raw_s
    if s in {"degraded", "warn", "warning", "partial", "slow", "lagging"}:
        return "degraded", raw_s
    if s in {"down", "offline", "error", "failed", "failure", "fatal", "critical", "unhealthy", "crashloop"}:
        return "down", raw_s
    if s in {"maintenance", "maint", "draining", "paused", "pause"}:
        return "maintenance", raw_s
    if s in {"unknown", "n/a", "na", "none", "null", "undefined", "?"}:
        return "unknown", raw_s
    if s in set(OPS_SERVICE_STATUSES):
        return s, raw_s
    return "unknown", raw_s


def _transition_allowed(prev: str, nxt: str) -> bool:
    p = (prev or "unknown").strip().lower() or "unknown"
    n = (nxt or "unknown").strip().lower() or "unknown"
    if p == n:
        return True
    if p in {"healthy", "degraded", "down", "maintenance"} and n == "unknown":
        return False
    return True


@dataclass(frozen=True)
class SourceInfo:
    topic: str
    message_id: str
    published_at: datetime


class FirestoreWriter:
    def __init__(self, *, project_id: str, database: str = "(default)", collection_prefix: str = "") -> None:
        from google.cloud import firestore as firestore_mod

        self._firestore = firestore_mod
        self._db = firestore_mod.Client(project=project_id, database=database)
        self._collection_prefix = str(collection_prefix or "").strip()

    def _col(self, name: str) -> str:
        p = self._collection_prefix
        return str(name) if not p else f"{p}{name}"

    def maybe_write_sampled_dlq_event(
        self,
        *,
        message_id: str,
        subscription: str,
        topic: str,
        handler: str,
        http_status: int,
        reason: str,
        error: str,
        delivery_attempt: Optional[int],
        attributes: dict[str, str],
        payload: Optional[dict[str, Any]],
        sample_rate: float,
        ttl_hours: float,
    ) -> bool:
        """
        Best-effort: record a sampled DLQ candidate under `sampled_dlq/{messageId}`.
        """
        try:
            r = float(sample_rate)
        except Exception:
            r = 0.0
        if r <= 0.0:
            return False
        mid = str(message_id or "").strip()
        if not mid:
            return False

        # Deterministic sampling per message_id.
        h = hashlib.sha256(mid.encode("utf-8")).hexdigest()
        pick = int(h[:8], 16) / float(0xFFFFFFFF)
        if pick > r:
            return False

        try:
            hours = float(ttl_hours)
        except Exception:
            hours = 72.0
        if hours <= 0:
            return False

        now = _utc_now()
        ref = self._db.collection(self._col("sampled_dlq")).document(mid.replace("/", "_"))
        doc: dict[str, Any] = {
            "messageId": mid,
            "subscription": str(subscription or ""),
            "topic": str(topic or ""),
            "handler": str(handler or ""),
            "httpStatus": int(http_status),
            "reason": str(reason or "")[:256],
            "error": str(error or "")[:2048],
            "deliveryAttempt": int(delivery_attempt) if delivery_attempt is not None else None,
            "attributes": dict(attributes or {}),
            "payload": payload or {},
            "receivedAt": now,
            "expiresAt": now + timedelta(hours=hours),
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        try:
            ref.set(doc, merge=False)
            return True
        except Exception:
            return False

    def observe_pubsub_delivery(
        self,
        *,
        message_id: str,
        topic: str,
        subscription: str,
        handler: str,
        published_at: datetime,
        delivery_attempt: Optional[int] = None,
    ) -> Optional[bool]:
        """
        Visibility-only: record Pub/Sub deliveries in `ops_pubsub_deliveries/{messageId}`.
        """
        mid = str(message_id or "").strip()
        if not mid:
            return None
        doc_id = mid.replace("/", "_")
        ref = self._db.collection(self._col("ops_pubsub_deliveries")).document(doc_id)
        try:
            ref.create(
                {
                    "messageId": mid,
                    "topic": str(topic or ""),
                    "subscription": str(subscription or ""),
                    "handler": str(handler or ""),
                    "publishedAt": _as_utc(published_at),
                    "deliveryAttempt": int(delivery_attempt) if delivery_attempt is not None else None,
                    "firstSeenAt": self._firestore.SERVER_TIMESTAMP,
                    "lastSeenAt": self._firestore.SERVER_TIMESTAMP,
                    "seenCount": 1,
                }
            )
            return False
        except Exception as e:
            try:
                from google.api_core.exceptions import AlreadyExists  # type: ignore
            except Exception:
                AlreadyExists = None  # type: ignore[assignment]
            if AlreadyExists is not None and isinstance(e, AlreadyExists):  # type: ignore[arg-type]
                try:
                    ref.set(
                        {
                            "lastSeenAt": self._firestore.SERVER_TIMESTAMP,
                            "seenCount": self._firestore.Increment(1),
                            "lastTopic": str(topic or ""),
                            "lastSubscription": str(subscription or ""),
                            "lastHandler": str(handler or ""),
                            "lastPublishedAt": _as_utc(published_at),
                            "lastDeliveryAttempt": int(delivery_attempt) if delivery_attempt is not None else None,
                        },
                        merge=True,
                    )
                except Exception:
                    pass
                return True
            return None

    def _upsert_event_doc(
        self,
        *,
        collection: str,
        doc_id: str,
        event_time: datetime,
        source: SourceInfo,
        doc: dict[str, Any],
        replay: Optional[ReplayContext] = None,
        replay_dedupe_key: Optional[str] = None,
    ) -> Tuple[bool, str]:
        ref = self._db.collection(self._col(collection)).document(str(doc_id))

        def _txn(txn: Any) -> Tuple[bool, str]:
            if replay is not None:
                ok, why = ensure_event_not_applied(
                    txn=txn,
                    db=self._db,
                    replay=replay,
                    dedupe_key=str(replay_dedupe_key or doc_id),
                    event_time=_as_utc(event_time),
                    message_id=str(source.message_id),
                )
                if not ok:
                    return False, why

            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_max = None
            if isinstance(existing, dict):
                existing_max = _max_dt(
                    _parse_rfc3339(existing.get("eventTime")),
                    _parse_rfc3339(existing.get("producedAt")),
                    _parse_rfc3339(existing.get("publishedAt")),
                    _parse_rfc3339((existing.get("source") or {}).get("publishedAt")) if isinstance(existing.get("source"), dict) else None,
                )

            incoming = _as_utc(event_time)
            if existing_max is not None and incoming < existing_max:
                return False, "stale_event_ignored"

            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

    def upsert_market_tick(
        self,
        *,
        doc_id: str,
        event_id: Optional[str],
        event_time: datetime,
        produced_at: Optional[datetime],
        published_at: Optional[datetime],
        symbol: Optional[str],
        data: dict[str, Any],
        source: SourceInfo,
        replay: Optional[ReplayContext] = None,
    ) -> Tuple[bool, str]:
        doc: dict[str, Any] = {
            "docId": str(doc_id),
            "eventId": str(event_id) if event_id else None,
            "symbol": str(symbol) if symbol else None,
            "eventTime": _as_utc(event_time),
            "producedAt": _as_utc(produced_at) if isinstance(produced_at, datetime) else None,
            "publishedAt": _as_utc(published_at) if isinstance(published_at, datetime) else None,
            "data": dict(data),
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "lastAppliedMessageId": str(source.message_id),
            "lastAppliedPublishedAt": _as_utc(source.published_at),
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
            "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="market_ticks",
            doc_id=str(doc_id),
            event_time=event_time,
            source=source,
            doc=doc,
            replay=replay,
            replay_dedupe_key=event_id or doc_id,
        )

    def upsert_market_bar_1m(
        self,
        *,
        doc_id: str,
        event_id: Optional[str],
        event_time: datetime,
        produced_at: Optional[datetime],
        published_at: Optional[datetime],
        symbol: Optional[str],
        timeframe: Optional[str],
        start: Optional[datetime],
        end: Optional[datetime],
        data: dict[str, Any],
        source: SourceInfo,
        replay: Optional[ReplayContext] = None,
    ) -> Tuple[bool, str]:
        doc: dict[str, Any] = {
            "docId": str(doc_id),
            "eventId": str(event_id) if event_id else None,
            "symbol": str(symbol) if symbol else None,
            "timeframe": str(timeframe) if timeframe else "1m",
            "start": _as_utc(start) if isinstance(start, datetime) else None,
            "end": _as_utc(end) if isinstance(end, datetime) else None,
            "eventTime": _as_utc(event_time),
            "producedAt": _as_utc(produced_at) if isinstance(produced_at, datetime) else None,
            "publishedAt": _as_utc(published_at) if isinstance(published_at, datetime) else None,
            "data": dict(data),
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "lastAppliedMessageId": str(source.message_id),
            "lastAppliedPublishedAt": _as_utc(source.published_at),
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
            "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="market_bars_1m",
            doc_id=str(doc_id),
            event_time=event_time,
            source=source,
            doc=doc,
            replay=replay,
            replay_dedupe_key=event_id or doc_id,
        )

    def upsert_trade_signal(
        self,
        *,
        doc_id: str,
        event_id: Optional[str],
        event_time: datetime,
        produced_at: Optional[datetime],
        published_at: Optional[datetime],
        symbol: Optional[str],
        strategy: Optional[str],
        action: Optional[str],
        data: dict[str, Any],
        source: SourceInfo,
        replay: Optional[ReplayContext] = None,
    ) -> Tuple[bool, str]:
        doc: dict[str, Any] = {
            "docId": str(doc_id),
            "eventId": str(event_id) if event_id else None,
            "symbol": str(symbol) if symbol else None,
            "strategy": str(strategy) if strategy else None,
            "action": str(action) if action else None,
            "eventTime": _as_utc(event_time),
            "producedAt": _as_utc(produced_at) if isinstance(produced_at, datetime) else None,
            "publishedAt": _as_utc(published_at) if isinstance(published_at, datetime) else None,
            "data": dict(data),
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "lastAppliedMessageId": str(source.message_id),
            "lastAppliedPublishedAt": _as_utc(source.published_at),
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
            "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="trade_signals",
            doc_id=str(doc_id),
            event_time=event_time,
            source=source,
            doc=doc,
            replay=replay,
            replay_dedupe_key=event_id or doc_id,
        )

    def dedupe_and_upsert_ops_service(
        self,
        *,
        message_id: str,
        replay: Optional[ReplayContext] = None,
        replay_dedupe_key: Optional[str] = None,
        service_id: str,
        env: str,
        status: str,
        last_heartbeat_at: Optional[datetime],
        version: str,
        region: str,
        updated_at: datetime,
        source: SourceInfo,
    ) -> Tuple[bool, str]:
        dedupe_ref = self._db.collection(self._col("ops_dedupe")).document(str(message_id))
        service_ref = self._db.collection(self._col("ops_services")).document(str(service_id))

        def _txn(txn: Any) -> Tuple[bool, str]:
            first, _existing = ensure_message_once(
                txn=txn,
                dedupe_ref=dedupe_ref,
                message_id=str(message_id),
                doc={"kind": "ops_services", "targetDoc": f"ops_services/{service_id}"},
            )
            if not first:
                return False, "duplicate_message_noop"

            if replay is not None:
                ok, why = ensure_event_not_applied(
                    txn=txn,
                    db=self._db,
                    replay=replay,
                    dedupe_key=str(replay_dedupe_key or message_id),
                    event_time=_as_utc(updated_at),
                    message_id=str(message_id),
                )
                if not ok:
                    return False, why

            snap = service_ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}
            existing_pub, existing_mid = _existing_pubsub_lww(existing)

            incoming_key = _lww_key(published_at=source.published_at, message_id=source.message_id)
            if existing_pub is not None and existing_mid is not None:
                existing_key = _lww_key(published_at=existing_pub, message_id=existing_mid)
                if incoming_key < existing_key:
                    txn.set(dedupe_ref, {"outcome": "out_of_order_ignored"}, merge=True)
                    return False, "out_of_order_event_ignored"

            prev_status, _ = _normalize_ops_service_status(existing.get("status") if isinstance(existing, dict) else None)
            next_status, raw_status = _normalize_ops_service_status(status)
            if not _transition_allowed(prev_status, next_status):
                next_status = prev_status
            if next_status == "unknown" and prev_status != "unknown":
                next_status = prev_status

            incoming_eff = _max_dt(_as_utc(updated_at), last_heartbeat_at, source.published_at) or _as_utc(updated_at)
            doc = {
                "serviceId": str(service_id),
                "env": str(env or "unknown"),
                "status": str(next_status),
                "status_raw": str(raw_status),
                "lastHeartbeatAt": _as_utc(last_heartbeat_at) if isinstance(last_heartbeat_at, datetime) else None,
                "version": str(version or "unknown"),
                "region": str(region or "unknown"),
                "updatedAt": incoming_eff,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                },
                "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
            }
            doc = {k: v for k, v in doc.items() if v is not None}
            txn.set(service_ref, doc, merge=True)
            txn.set(dedupe_ref, {"outcome": "applied"}, merge=True)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

    def dedupe_and_upsert_ingest_pipeline(
        self,
        *,
        message_id: str,
        pipeline_id: str,
        source: SourceInfo,
        fields: dict[str, Any],
    ) -> Tuple[bool, str]:
        dedupe_ref = self._db.collection(self._col("ingest_pipelines_dedupe")).document(str(message_id))
        pipeline_ref = self._db.collection(self._col("ingest_pipelines")).document(str(pipeline_id))

        def _txn(txn: Any) -> Tuple[bool, str]:
            first, _ = ensure_message_once(
                txn=txn,
                dedupe_ref=dedupe_ref,
                message_id=str(message_id),
                doc={"kind": "ingest_pipelines", "targetDoc": f"ingest_pipelines/{pipeline_id}"},
            )
            if not first:
                return False, "duplicate_message_noop"

            snap = pipeline_ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}
            existing_pub, existing_mid = _existing_pubsub_lww(existing)

            incoming_key = _lww_key(published_at=source.published_at, message_id=source.message_id)
            if existing_pub is not None and existing_mid is not None:
                existing_key = _lww_key(published_at=existing_pub, message_id=existing_mid)
                if incoming_key < existing_key:
                    txn.set(dedupe_ref, {"outcome": "out_of_order_ignored"}, merge=True)
                    return False, "out_of_order_event_ignored"

            doc: dict[str, Any] = {
                "pipelineId": str(pipeline_id),
                "source": {"topic": str(source.topic), "messageId": str(source.message_id), "publishedAt": _as_utc(source.published_at)},
                "publishedAt": _as_utc(source.published_at),
                "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
            }
            for k, v in (fields or {}).items():
                if v is not None:
                    doc[str(k)] = v

            txn.set(service_ref, doc, merge=True)
            txn.set(dedupe_ref, {"outcome": "applied"}, merge=True)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

    def dedupe_and_upsert_ingest_pipeline(
        self,
        *,
        message_id: str,
        pipeline_id: str,
        source: SourceInfo,
        fields: dict[str, Any],
        replay: Optional[ReplayContext] = None,
        replay_dedupe_key: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Transactionally:
        - dedupe on `ops_dedupe/{messageId}`
        - last-write-wins on `ingest_pipelines/{pipelineId}` using Pub/Sub publishedAt (+ messageId tie-break)
        """
        dedupe_ref = self._db.collection(self._col("ops_dedupe")).document(str(message_id))
        pipeline_ref = self._db.collection(self._col("ingest_pipelines")).document(str(pipeline_id))

        def _txn(txn: Any) -> Tuple[bool, str]:
            first_time, _ = ensure_message_once(
                txn=txn,
                dedupe_ref=dedupe_ref,
                message_id=str(message_id),
                doc={
                    "kind": "ingest_pipelines",
                    "targetDoc": f"ingest_pipelines/{pipeline_id}",
                    "sourceTopic": str(source.topic),
                    "sourcePublishedAt": _as_utc(source.published_at),
                },
            )
            if not first_time:
                return False, "duplicate_message_noop"

            if replay is not None:
                ok, why = ensure_event_not_applied(
                    txn=txn,
                    db=self._db,
                    replay=replay,
                    dedupe_key=str(replay_dedupe_key or message_id),
                    event_time=_as_utc(source.published_at),
                    message_id=str(message_id),
                )
                if not ok:
                    return False, why

            snap = pipeline_ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}
            existing_pub, existing_mid = _existing_pubsub_lww(existing if isinstance(existing, dict) else {})
            if existing_pub is not None:
                inc_key = _lww_key(published_at=source.published_at, message_id=str(source.message_id))
                ex_key = _lww_key(published_at=existing_pub, message_id=str(existing_mid or ""))
                if inc_key < ex_key:
                    txn.set(
                        dedupe_ref,
                        {
                            "outcome": "out_of_order_ignored",
                            "reason": "incoming_publishedAt_older_than_stored",
                            "storedPublishedAt": existing_pub,
                            "storedMessageId": existing_mid,
                        },
                        merge=True,
                    )
                    return False, "out_of_order_event_ignored"

            doc: dict[str, Any] = {
                "pipelineId": str(pipeline_id),
                "publishedAt": _as_utc(source.published_at),
                "published_at": _as_utc(source.published_at),
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "message_id": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                    "published_at": _as_utc(source.published_at),
                },
                "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
            }
            for k, v in (fields or {}).items():
                if v is not None:
                    doc[str(k)] = v
            txn.set(pipeline_ref, doc, merge=True)
            txn.set(dedupe_ref, {"outcome": "applied"}, merge=True)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)


__all__ = [
    "SourceInfo",
    "FirestoreWriter",
    "_existing_pubsub_lww",
    "_lww_key",
]
