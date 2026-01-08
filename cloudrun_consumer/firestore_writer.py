from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from google.cloud import firestore

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
        self._db = firestore.Client(project=project_id, database=database)

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
        - only overwrite if incoming `updated_at` >= max(stored.lastHeartbeatAt, stored.updatedAt)
        """
        ref = self._db.collection("ops_services").document(service_id)

        @firestore.transactional
        def _txn(txn: firestore.Transaction) -> Tuple[bool, str]:
            snap = ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_u = _parse_rfc3339(existing.get("updatedAt")) if isinstance(existing, dict) else None
            existing_max = _max_dt(existing_lh, existing_u)

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
                "updatedAt": incoming,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                },
            }

            txn.set(ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return _txn(txn)

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

        @firestore.transactional
        def _txn(txn: firestore.Transaction) -> Tuple[bool, str]:
            first_time, _ = ensure_message_once(txn=txn, dedupe_ref=dedupe_ref, message_id=message_id)
            if not first_time:
                return False, "duplicate_message_noop"

            snap = service_ref.get(transaction=txn)
            existing = snap.to_dict() if snap.exists else {}

            existing_lh = _parse_rfc3339(existing.get("lastHeartbeatAt")) if isinstance(existing, dict) else None
            existing_u = _parse_rfc3339(existing.get("updatedAt")) if isinstance(existing, dict) else None
            existing_max = _max_dt(existing_lh, existing_u)

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
                "updatedAt": incoming,
                "source": {
                    "topic": str(source.topic),
                    "messageId": str(source.message_id),
                    "publishedAt": _as_utc(source.published_at),
                },
            }

            txn.set(service_ref, doc)
            return True, "applied"

        txn = self._db.transaction()
        return _txn(txn)

