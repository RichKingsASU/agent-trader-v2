from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from google.api_core import exceptions as gexc

from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_doc_id(*, scope: str, key: str) -> str:
    """
    Firestore doc IDs can be long, but we keep these compact and uniform.
    """
    raw = f"{scope}|{key}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:48]


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    tenant_id: str
    scope: str
    key: str
    status: str  # "started" | "completed" | "failed"
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    outcome: Optional[dict[str, Any]]


class FirestoreIdempotencyStore:
    """
    A minimal idempotency store for side effects.

    Storage:
      tenants/{tenant_id}/idempotency/{docId}

    Semantics:
    - `begin(...)` uses Firestore `create()` to guarantee a single winner.
    - Callers MAY write `complete(...)` with an outcome payload for replay-safe returns.
    """

    def __init__(self, *, project_id: str | None = None, collection_name: str = "idempotency") -> None:
        self._db = get_firestore_client(project_id=project_id)
        self._collection_name = str(collection_name).strip() or "idempotency"

    def _ref(self, *, tenant_id: str, scope: str, key: str):
        doc_id = _stable_doc_id(scope=scope, key=key)
        return (
            self._db.collection("tenants")
            .document(str(tenant_id))
            .collection(self._collection_name)
            .document(doc_id)
        )

    def begin(
        self,
        *,
        tenant_id: str,
        scope: str,
        key: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[bool, IdempotencyRecord]:
        """
        Returns (acquired, record).

        - acquired=True: caller is the first processor and should perform the side effect
        - acquired=False: duplicate; caller MUST NOT perform the side effect
        """
        tenant_id_s = str(tenant_id).strip()
        scope_s = str(scope).strip()
        key_s = str(key).strip()
        if not tenant_id_s:
            raise ValueError("tenant_id is required for idempotency")
        if not scope_s:
            raise ValueError("scope is required for idempotency")
        if not key_s:
            raise ValueError("key is required for idempotency")

        ref = self._ref(tenant_id=tenant_id_s, scope=scope_s, key=key_s)
        now = _utc_now()

        doc: dict[str, Any] = {
            "tenant_id": tenant_id_s,
            "scope": scope_s,
            "key": key_s,
            "status": "started",
            "created_at": now,
            "updated_at": now,
        }
        if payload:
            doc["payload"] = dict(payload)

        try:
            with_firestore_retry(lambda: ref.create(doc))
            return True, IdempotencyRecord(
                tenant_id=tenant_id_s,
                scope=scope_s,
                key=key_s,
                status="started",
                created_at=now,
                updated_at=now,
                outcome=None,
            )
        except gexc.AlreadyExists:
            snap = with_firestore_retry(lambda: ref.get())
            existing = snap.to_dict() if snap.exists else {}
            return False, IdempotencyRecord(
                tenant_id=tenant_id_s,
                scope=scope_s,
                key=key_s,
                status=str((existing or {}).get("status") or "started"),
                created_at=(existing or {}).get("created_at"),
                updated_at=(existing or {}).get("updated_at"),
                outcome=(existing or {}).get("outcome") if isinstance((existing or {}).get("outcome"), dict) else None,
            )

    def complete(
        self,
        *,
        tenant_id: str,
        scope: str,
        key: str,
        outcome: dict[str, Any],
        status: str = "completed",
    ) -> None:
        tenant_id_s = str(tenant_id).strip()
        scope_s = str(scope).strip()
        key_s = str(key).strip()
        if not tenant_id_s or not scope_s or not key_s:
            raise ValueError("tenant_id/scope/key are required for idempotency completion")

        if status not in {"completed", "failed"}:
            raise ValueError("status must be 'completed' or 'failed'")

        ref = self._ref(tenant_id=tenant_id_s, scope=scope_s, key=key_s)
        now = _utc_now()
        patch = {"status": status, "updated_at": now, "outcome": dict(outcome or {})}
        with_firestore_retry(lambda: ref.set(patch, merge=True))

