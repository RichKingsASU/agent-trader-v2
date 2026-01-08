from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import sys
import traceback
from typing import Any, Optional, Tuple

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
        try:
            sys.stderr.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "severity": "ERROR",
                        "event_type": "firestore_writer.parse_rfc3339_failed",
                        "value": s[:256],
                        "exception": traceback.format_exc()[-8000:],
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stderr.flush()
        except Exception:
            pass
        return None


def _max_dt(*values: Optional[datetime]) -> Optional[datetime]:
    xs = [v for v in values if isinstance(v, datetime)]
    if not xs:
        return None
    return max(_as_utc(v) for v in xs)


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
        if not p:
            return str(name)
        # Keep simple; prefix should be Firestore-safe (no '/').
        return f"{p}{name}"

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
        Visibility-only: record that a Pub/Sub push delivery occurred.

        Returns:
        - True if this messageId has been seen before (duplicate delivery)
        - False if first observation
        - None if observation failed (best-effort)

        IMPORTANT: this method must not be used to gate processing.
        """
        mid = str(message_id or "").strip()
        if not mid:
            return None

        # Firestore doc ids cannot contain '/'.
        doc_id = mid.replace("/", "_")
        ref = self._db.collection("ops_pubsub_deliveries").document(doc_id)

        try:
            # Prefer create() so we can detect duplicates without reads.
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
            # If it already exists, we treat as duplicate delivery and update counters best-effort.
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
                    # Observation must never break processing.
                    pass
                return True

            # Unknown failure: treat as "no observation" (visibility only).
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
        """
        Generic upsert with stale protection:
        - doc id is deterministic (eventId if present else messageId)
        - ignore stale updates based on event_time vs existing produced/published/eventTime/source.publishedAt
        """
        ref = self._db.collection(self._col(collection)).document(doc_id)

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

            existing_event_time = None
            if isinstance(existing, dict):
                existing_event_time = _parse_rfc3339(existing.get("eventTime"))
                existing_produced_at = _parse_rfc3339(existing.get("producedAt"))
                existing_published_at = _parse_rfc3339(existing.get("publishedAt"))
                existing_source_pub = None
                src = existing.get("source")
                if isinstance(src, dict):
                    existing_source_pub = _parse_rfc3339(src.get("publishedAt"))
                existing_max = _max_dt(existing_event_time, existing_produced_at, existing_published_at, existing_source_pub)
            else:
                existing_max = None

            incoming = _as_utc(event_time)
            if existing_max is not None and incoming < existing_max:
                return False, "stale_event_ignored"

            protected = self._protect_published_at(existing=existing or {}, incoming_doc=doc)
            txn.set(ref, protected)
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
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "eventTime": _as_utc(event_time),
            "producedAt": ensure_utc(produced_at, source="cloudrun_consumer.firestore_writer.upsert_market_tick", field="produced_at") if isinstance(produced_at, datetime) else produced_at,
            "publishedAt": ensure_utc(published_at, source="cloudrun_consumer.firestore_writer.upsert_market_tick", field="published_at") if isinstance(published_at, datetime) else published_at,
            "data": data,
            "lastAppliedMessageId": str(source.message_id),
            "lastAppliedPublishedAt": _as_utc(source.published_at),
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
            "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
        }
        # Remove nulls for cleaner docs.
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="market_ticks",
            doc_id=doc_id,
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
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "timeframe": timeframe or "1m",
            "start": ensure_utc(start, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="start") if isinstance(start, datetime) else start,
            "end": ensure_utc(end, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="end") if isinstance(end, datetime) else end,
            "eventTime": _as_utc(event_time),
            "producedAt": ensure_utc(produced_at, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="produced_at") if isinstance(produced_at, datetime) else produced_at,
            "publishedAt": ensure_utc(published_at, source="cloudrun_consumer.firestore_writer.upsert_market_bar_1m", field="published_at") if isinstance(published_at, datetime) else published_at,
            "data": data,
            "lastAppliedMessageId": str(source.message_id),
            "lastAppliedPublishedAt": _as_utc(source.published_at),
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
            "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="market_bars_1m",
            doc_id=doc_id,
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
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "strategy": strategy,
            "action": action,
            "eventTime": _as_utc(event_time),
            "producedAt": ensure_utc(produced_at, source="cloudrun_consumer.firestore_writer.upsert_trade_signal", field="produced_at") if isinstance(produced_at, datetime) else produced_at,
            "publishedAt": ensure_utc(published_at, source="cloudrun_consumer.firestore_writer.upsert_trade_signal", field="published_at") if isinstance(published_at, datetime) else published_at,
            "data": data,
            "lastAppliedMessageId": str(source.message_id),
            "lastAppliedPublishedAt": _as_utc(source.published_at),
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
            "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(
            collection="trade_signals",
            doc_id=doc_id,
            event_time=event_time,
            source=source,
            doc=doc,
            replay=replay,
            replay_dedupe_key=event_id or doc_id,
        )

    def upsert_ops_service(
        self,
        *,
        service_id: str,
        env: str,
        status: str,
        last_heartbeat_at: Optional[datetime],
        version: str,
        region: str,
        updated_at: datetime,
        source: SourceInfo,
    ) -> Tuple[bool, str]:
        """
        Writes `ops_services/{serviceId}` with last-write-wins ordering.

        Ordering rule (per mission):
        - only overwrite if incoming `source.published_at` >= stored `publishedAt`/`source.publishedAt`
        - tie-breaker: `source.messageId` lexicographic
        """
        ref = self._db.collection(self._col("ops_services")).document(service_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_source_pub = None
            if isinstance(existing, dict):
                src = existing.get("source")
                if isinstance(src, dict):
                    existing_source_pub = _parse_rfc3339(src.get("publishedAt"))

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_lh_sc = _parse_rfc3339(existing.get("last_heartbeat_at")) if isinstance(existing, dict) else None
            existing_u = _parse_rfc3339(existing.get("updatedAt")) if isinstance(existing, dict) else None
            existing_u_sc = _parse_rfc3339(existing.get("updated_at")) if isinstance(existing, dict) else None
            existing_max = _max_dt(existing_lh, existing_lh_sc, existing_u, existing_u_sc, existing_source_pub)

            incoming = _as_utc(updated_at)
            incoming_eff = _max_dt(incoming, last_heartbeat_at, source.published_at) or incoming
            if existing_max is not None and incoming_eff < existing_max:
                return False, "stale_event_ignored"

            prev_status, _ = _normalize_ops_service_status(existing.get("status") if isinstance(existing, dict) else None)
            next_status, raw_status = _normalize_ops_service_status(status)
            if not _transition_allowed(prev_status, next_status):
                next_status = prev_status
            if next_status == "unknown" and prev_status != "unknown":
                next_status = prev_status

            doc = {
                "serviceId": str(service_id),
                "service_id": str(service_id),
                "env": str(env),
                "environment": str(env),
                "status": str(next_status),
                "status_raw": str(raw_status),
                "lastHeartbeatAt": last_heartbeat_at,
                "last_heartbeat_at": last_heartbeat_at,
                "version": str(version),
                "region": str(region),
                "updatedAt": incoming_eff,
                "updated_at": incoming_eff,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "message_id": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                    "published_at": _as_utc(source.published_at),
                },
                "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
            }

            txn.set(ref, doc, merge=True)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

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
        """
        Transactionally:
        - checks/creates `ops_dedupe/{messageId}`
        - applies last-write-wins write to ops_services using `publishedAt`
        - records outcome metadata on the dedupe doc for visibility
        """
        dedupe_ref = self._db.collection(self._col("ops_dedupe")).document(message_id)
        service_ref = self._db.collection(self._col("ops_services")).document(service_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
            first_time, _ = ensure_message_once(
                txn=txn,
                dedupe_ref=dedupe_ref,
                message_id=message_id,
                doc={
                    "kind": "ops_services",
                    "targetDoc": f"ops_services/{service_id}",
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
                    event_time=_as_utc(updated_at),
                    message_id=str(message_id),
                )
                if not ok:
                    return False, why

            snap = service_ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_source_pub = None
            if isinstance(existing, dict):
                src = existing.get("source")
                if isinstance(src, dict):
                    existing_source_pub = _parse_rfc3339(src.get("publishedAt"))

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_lh_sc = _parse_rfc3339(existing.get("last_heartbeat_at")) if isinstance(existing, dict) else None
            existing_u = _parse_rfc3339(existing.get("updatedAt")) if isinstance(existing, dict) else None
            existing_u_sc = _parse_rfc3339(existing.get("updated_at")) if isinstance(existing, dict) else None
            existing_max = _max_dt(existing_lh, existing_lh_sc, existing_u, existing_u_sc, existing_source_pub)

            incoming = _as_utc(updated_at)
            incoming_eff = _max_dt(incoming, last_heartbeat_at, source.published_at) or incoming
            if existing_max is not None and incoming_eff < existing_max:
                # Marked dedupe already; do not reprocess on retries.
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

            prev_status, _ = _normalize_ops_service_status(existing.get("status") if isinstance(existing, dict) else None)
            next_status, raw_status = _normalize_ops_service_status(status)
            if not _transition_allowed(prev_status, next_status):
                next_status = prev_status
            if next_status == "unknown" and prev_status != "unknown":
                next_status = prev_status

            doc = {
                "serviceId": str(service_id),
                "service_id": str(service_id),
                "env": str(env),
                "environment": str(env),
                "status": str(next_status),
                "status_raw": str(raw_status),
                "lastHeartbeatAt": last_heartbeat_at,
                "last_heartbeat_at": last_heartbeat_at,
                "version": str(version),
                "region": str(region),
                "updatedAt": incoming_eff,
                "updated_at": incoming_eff,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "message_id": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                    "published_at": _as_utc(source.published_at),
                },
                "lastAppliedAt": self._firestore.SERVER_TIMESTAMP,
            }
            if isinstance(fields, dict) and fields:
                for k, v in fields.items():
                    if v is not None:
                        doc[k] = v

            txn.set(pipeline_ref, doc, merge=True)
            txn.set(dedupe_ref, {"outcome": "applied"}, merge=True)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

