from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol, runtime_checkable

from backend.persistence.firestore_retry import with_firestore_retry

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@runtime_checkable
class ReservationHandle(Protocol):
    """
    Handle for an in-flight reservation.

    Contract:
    - `release()` MUST be safe to call multiple times.
    - `release()` MUST NOT raise (best-effort cleanup).
    """

    def release(self, *, outcome: str, error: str | None = None) -> None: ...


@runtime_checkable
class ReservationManager(Protocol):
    """
    Best-effort reservation manager.

    IMPORTANT: This is NOT a retry/queue system. It is a local, per-execution
    cleanup guard so a failed trade cannot leak "reserved" state that blocks
    subsequent trades.
    """

    def reserve(
        self,
        *,
        tenant_id: str,
        broker_account_id: str,
        client_intent_id: str,
        amount_usd: float,
        ttl_seconds: int = 300,
        meta: dict[str, Any] | None = None,
    ) -> ReservationHandle: ...


@dataclass
class NoopReservation(ReservationHandle):
    def release(self, *, outcome: str, error: str | None = None) -> None:  # noqa: ARG002
        return


class BestEffortReservationManager:
    """
    Wrap a ReservationManager so reserve/release never raises.
    """

    def __init__(self, inner: ReservationManager | None):
        self._inner = inner

    def reserve(
        self,
        *,
        tenant_id: str,
        broker_account_id: str,
        client_intent_id: str,
        amount_usd: float,
        ttl_seconds: int = 300,
        meta: dict[str, Any] | None = None,
    ) -> ReservationHandle:
        if self._inner is None:
            return NoopReservation()
        try:
            return self._inner.reserve(
                tenant_id=tenant_id,
                broker_account_id=broker_account_id,
                client_intent_id=client_intent_id,
                amount_usd=float(amount_usd),
                ttl_seconds=int(ttl_seconds),
                meta=meta,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "exec.reservation.reserve_failed tenant_id=%s broker_account_id=%s client_intent_id=%s error=%s",
                tenant_id,
                broker_account_id,
                client_intent_id,
                f"{type(e).__name__}: {e}",
            )
            return NoopReservation()


class _FirestoreReservationHandle(ReservationHandle):
    def __init__(self, *, doc_ref, reservation_id: str):
        self._doc_ref = doc_ref
        self._reservation_id = str(reservation_id)
        self._released = False

    def release(self, *, outcome: str, error: str | None = None) -> None:
        if self._released:
            return
        self._released = True
        try:
            with_firestore_retry(
                lambda: self._doc_ref.set(
                    {
                        "status": "released",
                        "released_at": _utc_now(),
                        "released_at_iso": _utc_now().isoformat(),
                        "release_outcome": str(outcome),
                        "release_error": str(error) if error else None,
                    },
                    merge=True,
                )
            )
        except Exception as e:  # noqa: BLE001
            # Cleanup must never throw.
            logger.warning(
                "exec.reservation.release_failed reservation_id=%s error=%s",
                self._reservation_id,
                f"{type(e).__name__}: {e}",
            )


class FirestoreReservationManager:
    """
    Firestore-backed in-flight reservation tracking.

    Storage:
      tenants/{tenant_id}/execution_reservations/{client_intent_id}
    """

    def __init__(self, *, collection_name: str = "execution_reservations"):
        self._collection_name = str(collection_name)

    def reserve(
        self,
        *,
        tenant_id: str,
        broker_account_id: str,
        client_intent_id: str,
        amount_usd: float,
        ttl_seconds: int = 300,
        meta: dict[str, Any] | None = None,
    ) -> ReservationHandle:
        from backend.persistence.firebase_client import get_firestore_client

        tenant_id = str(tenant_id).strip()
        broker_account_id = str(broker_account_id).strip()
        client_intent_id = str(client_intent_id).strip()
        if not tenant_id or not client_intent_id:
            return NoopReservation()

        db = get_firestore_client()
        doc_ref = (
            db.collection("tenants")
            .document(tenant_id)
            .collection(self._collection_name)
            .document(client_intent_id)
        )

        now = _utc_now()
        expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
        payload: dict[str, Any] = {
            "reservation_id": client_intent_id,
            "tenant_id": tenant_id,
            "broker_account_id": broker_account_id,
            "client_intent_id": client_intent_id,
            "amount_usd": float(amount_usd or 0.0),
            "status": "reserved",
            "created_at": now,
            "created_at_iso": now.isoformat(),
            # TTL: can be configured in Firestore to auto-delete.
            "expires_at": expires_at,
            "expires_at_iso": expires_at.isoformat(),
            "meta": dict(meta or {}),
            "agent_name": str(os.getenv("AGENT_NAME") or "").strip() or None,
        }

        def _create_or_merge() -> None:
            # Prefer create() to avoid overwriting if a duplicate attempt uses the same id.
            # If it already exists, merge a last-seen marker but keep original fields.
            try:
                doc_ref.create(payload)
            except Exception:
                doc_ref.set(
                    {
                        "last_seen_at": now,
                        "last_seen_at_iso": now.isoformat(),
                        "status": "reserved",
                    },
                    merge=True,
                )

        with_firestore_retry(_create_or_merge)
        return _FirestoreReservationHandle(doc_ref=doc_ref, reservation_id=client_intent_id)


def resolve_tenant_id_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    md = dict(metadata or {})
    tenant_id = str(md.get("tenant_id") or "").strip()
    if not tenant_id:
        tenant_id = str(os.getenv("EXEC_TENANT_ID") or os.getenv("TENANT_ID") or "").strip()
    return tenant_id or None

