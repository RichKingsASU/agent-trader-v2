from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class IdempotencyClaim:
    message_id: str
    already_done: bool
    doc_path: str


class IdempotencyStore:
    """
    At-least-once safe dedupe using Pub/Sub messageId.

    Implementation notes:
    - Writes a single doc keyed by messageId using create() (fails if exists).
    - Uses Firestore TTL via expireAt (no explicit deletions).
    """

    def __init__(
        self,
        client: Optional[firestore.Client] = None,
        collection: Optional[str] = None,
        ttl_days: Optional[int] = None,
    ) -> None:
        self._db = client or firestore.Client()
        self._collection = collection or os.getenv("IDEMPOTENCY_COLLECTION", "_ops_dedup")
        self._ttl_days = ttl_days if ttl_days is not None else int(os.getenv("IDEMPOTENCY_TTL_DAYS", "7"))

    def begin(self, message_id: str, published_at: datetime, extra: Optional[Dict[str, Any]] = None) -> IdempotencyClaim:
        published_at = _ensure_utc(published_at)
        doc_ref = self._db.collection(self._collection).document(message_id)
        expire_at = _utc_now() + timedelta(days=self._ttl_days)

        txn = self._db.transaction()

        @firestore.transactional
        def _tx(transaction: firestore.Transaction) -> IdempotencyClaim:
            snap = doc_ref.get(transaction=transaction)
            if snap.exists:
                existing = snap.to_dict() or {}
                if str(existing.get("status") or "").lower() == "done":
                    return IdempotencyClaim(message_id=message_id, already_done=True, doc_path=doc_ref.path)

                # Not done yet: allow processing/retry. Keep a heartbeat of attempts.
                updates: Dict[str, Any] = {
                    "status": "processing",
                    "lastAttemptAt": firestore.SERVER_TIMESTAMP,
                }
                if extra:
                    updates["extra"] = extra
                transaction.set(doc_ref, updates, merge=True)
                return IdempotencyClaim(message_id=message_id, already_done=False, doc_path=doc_ref.path)

            payload: Dict[str, Any] = {
                "messageId": message_id,
                "publishedAt": published_at,
                "status": "processing",
                "firstSeenAt": firestore.SERVER_TIMESTAMP,
                "lastAttemptAt": firestore.SERVER_TIMESTAMP,
                "expireAt": expire_at,  # configure TTL on this field in Firestore (optional).
            }
            if extra:
                payload["extra"] = extra
            transaction.create(doc_ref, payload)
            return IdempotencyClaim(message_id=message_id, already_done=False, doc_path=doc_ref.path)

        return _tx(txn)

    def mark_done(self, message_id: str, extra: Optional[Dict[str, Any]] = None) -> None:
        doc_ref = self._db.collection(self._collection).document(message_id)
        updates: Dict[str, Any] = {
            "status": "done",
            "doneAt": firestore.SERVER_TIMESTAMP,
        }
        if extra:
            updates["extra"] = extra
        doc_ref.set(updates, merge=True)
