from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import sys
import traceback
from typing import Any, Optional, Tuple

from idempotency import ensure_message_once


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_rfc3339(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return _as_utc(dt)
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


@dataclass(frozen=True)
class SourceInfo:
    topic: str
    message_id: str
    published_at: datetime


class FirestoreWriter:
    def __init__(self, *, project_id: str, database: str = "(default)") -> None:
        from google.cloud import firestore as firestore_mod

        self._firestore = firestore_mod
        self._db = firestore_mod.Client(project=project_id, database=database)

    def _protect_published_at(self, *, existing: dict[str, Any], incoming_doc: dict[str, Any]) -> dict[str, Any]:
        """
        Best-effort monotonic protection for fields that may be used for ordering.

        Invariants:
        - If a document already has `publishedAt`, we never move it backwards.
        - If a document already has `source.publishedAt`, we never move it backwards.

        Note: This does NOT add new fields; it only prevents regressions.
        """
        out = dict(incoming_doc)
        if not isinstance(existing, dict):
            return out

        existing_published_at = _parse_rfc3339(existing.get("publishedAt"))
        incoming_published_at = _parse_rfc3339(out.get("publishedAt"))
        if existing_published_at is not None and incoming_published_at is not None and incoming_published_at < existing_published_at:
            out["publishedAt"] = existing_published_at

        existing_src = existing.get("source")
        incoming_src = out.get("source")
        existing_source_pub = _parse_rfc3339(existing_src.get("publishedAt")) if isinstance(existing_src, dict) else None
        incoming_source_pub = _parse_rfc3339(incoming_src.get("publishedAt")) if isinstance(incoming_src, dict) else None
        if (
            isinstance(incoming_src, dict)
            and existing_source_pub is not None
            and incoming_source_pub is not None
            and incoming_source_pub < existing_source_pub
        ):
            fixed_src = dict(incoming_src)
            fixed_src["publishedAt"] = existing_source_pub
            out["source"] = fixed_src

        return out

    def _upsert_event_doc(
        self,
        *,
        collection: str,
        doc_id: str,
        event_time: datetime,
        source: SourceInfo,
        doc: dict[str, Any],
    ) -> Tuple[bool, str]:
        """
        Generic upsert with stale protection:
        - doc id is deterministic (eventId if present else messageId)
        - ignore stale updates based on event_time vs existing produced/published/eventTime/source.publishedAt
        """
        ref = self._db.collection(collection).document(doc_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
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
    ) -> Tuple[bool, str]:
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "eventTime": _as_utc(event_time),
            "producedAt": produced_at,
            "publishedAt": published_at,
            "data": data,
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
        }
        # Remove nulls for cleaner docs.
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(collection="market_ticks", doc_id=doc_id, event_time=event_time, source=source, doc=doc)

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
    ) -> Tuple[bool, str]:
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "timeframe": timeframe or "1m",
            "start": start,
            "end": end,
            "eventTime": _as_utc(event_time),
            "producedAt": produced_at,
            "publishedAt": published_at,
            "data": data,
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(collection="market_bars_1m", doc_id=doc_id, event_time=event_time, source=source, doc=doc)

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
    ) -> Tuple[bool, str]:
        doc = {
            "docId": doc_id,
            "eventId": event_id,
            "symbol": symbol,
            "strategy": strategy,
            "action": action,
            "eventTime": _as_utc(event_time),
            "producedAt": produced_at,
            "publishedAt": published_at,
            "data": data,
            "source": {
                "topic": str(source.topic),
                "messageId": str(source.message_id),
                "publishedAt": _as_utc(source.published_at),
            },
            "ingestedAt": self._firestore.SERVER_TIMESTAMP,
        }
        doc = {k: v for k, v in doc.items() if v is not None}
        return self._upsert_event_doc(collection="trade_signals", doc_id=doc_id, event_time=event_time, source=source, doc=doc)

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
        Writes `ops_services/{serviceId}` with stale protection.

        Stale protection rule (per mission):
        - only overwrite if incoming `updated_at` >= max(stored.lastHeartbeatAt, stored.source.publishedAt)
        - `updatedAt` stored in Firestore is always a server timestamp (write time)
        """
        ref = self._db.collection("ops_services").document(service_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_source_pub = None
            if isinstance(existing, dict):
                src = existing.get("source")
                if isinstance(src, dict):
                    existing_source_pub = _parse_rfc3339(src.get("publishedAt"))
            existing_max = _max_dt(existing_lh, existing_source_pub)

            incoming = _as_utc(updated_at)
            if existing_max is not None and incoming < existing_max:
                return False, "stale_event_ignored"

            doc = {
                "serviceId": str(service_id),
                "env": str(env),
                "status": str(status),
                "lastHeartbeatAt": last_heartbeat_at,
                "version": str(version),
                "region": str(region),
                # Correctness: always server timestamp (never client/event-provided time).
                "updatedAt": self._firestore.SERVER_TIMESTAMP,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                },
            }

            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

    def dedupe_and_upsert_ops_service(
        self,
        *,
        message_id: str,
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
        - applies stale-protected write to ops_services
        """
        dedupe_ref = self._db.collection("ops_dedupe").document(message_id)
        service_ref = self._db.collection("ops_services").document(service_id)

        def _txn(txn: Any) -> Tuple[bool, str]:
            first_time, _ = ensure_message_once(txn=txn, dedupe_ref=dedupe_ref, message_id=message_id)
            if not first_time:
                return False, "duplicate_message_noop"

            snap = service_ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_source_pub = None
            if isinstance(existing, dict):
                src = existing.get("source")
                if isinstance(src, dict):
                    existing_source_pub = _parse_rfc3339(src.get("publishedAt"))
            existing_max = _max_dt(existing_lh, existing_source_pub)

            incoming = _as_utc(updated_at)
            if existing_max is not None and incoming < existing_max:
                # Marked dedupe already; do not reprocess on retries.
                return False, "stale_event_ignored"

            doc = {
                "serviceId": str(service_id),
                "env": str(env),
                "status": str(status),
                "lastHeartbeatAt": last_heartbeat_at,
                "version": str(version),
                "region": str(region),
                # Correctness: always server timestamp (never client/event-provided time).
                "updatedAt": self._firestore.SERVER_TIMESTAMP,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                },
            }

            txn.set(service_ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return self._firestore.transactional(_txn)(txn)

