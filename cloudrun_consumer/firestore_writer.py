from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class SourceContext:
    message_id: str
    published_at: datetime
    topic: str


class FirestoreWriter:
    """
    Firestore read-model writer with a single rule:
    - never delete
    - only overwrite when incoming source.publishedAt is newer
    """

    def __init__(self, client: Optional[firestore.Client] = None) -> None:
        self._db = client or firestore.Client()

    @property
    def db(self) -> firestore.Client:
        return self._db

    def upsert_ops_service(self, service_id: str, source: SourceContext, fields: Dict[str, Any]) -> bool:
        return self._upsert_if_newer(
            collection="ops_services",
            doc_id=service_id,
            source=source,
            fields=fields,
        )

    def upsert_ingest_pipeline(self, pipeline_id: str, source: SourceContext, fields: Dict[str, Any]) -> bool:
        return self._upsert_if_newer(
            collection="ingest_pipelines",
            doc_id=pipeline_id,
            source=source,
            fields=fields,
        )

    def _upsert_if_newer(
        self,
        collection: str,
        doc_id: str,
        source: SourceContext,
        fields: Dict[str, Any],
    ) -> bool:
        source_published_at = _ensure_utc(source.published_at)
        doc_ref = self._db.collection(collection).document(doc_id)
        txn = self._db.transaction()

        @firestore.transactional
        def _tx(transaction: firestore.Transaction) -> bool:
            snap = doc_ref.get(transaction=transaction)
            if snap.exists:
                existing = snap.to_dict() or {}
                existing_source = (existing.get("source") or {}) if isinstance(existing.get("source"), dict) else {}
                existing_published_at = existing_source.get("publishedAt")
                if isinstance(existing_published_at, datetime):
                    existing_published_at = _ensure_utc(existing_published_at)
                    if existing_published_at >= source_published_at:
                        return False

            payload: Dict[str, Any] = {
                **fields,
                "updatedAt": firestore.SERVER_TIMESTAMP,
                "source": {
                    "messageId": source.message_id,
                    "publishedAt": source_published_at,
                    "topic": source.topic,
                },
            }

            # merge=True ensures we never "delete" fields by omission.
            transaction.set(doc_ref, payload, merge=True)
            return True

        return _tx(txn)
