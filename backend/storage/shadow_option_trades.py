from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Tuple
from uuid import UUID

try:  # pragma: no cover
    from google.api_core import exceptions as gexc
except Exception:  # pragma: no cover
    gexc = None  # type: ignore[assignment]

try:  # pragma: no cover
    from google.cloud import firestore
except Exception:  # pragma: no cover
    firestore = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        try:
            return dict(asdict(value))
        except Exception:
            return {}
    fn = getattr(value, "to_dict", None)
    if callable(fn):
        try:
            out = fn()
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:
            return {}
    # Pydantic v2
    fn = getattr(value, "model_dump", None)
    if callable(fn):
        try:
            out = fn()
            return dict(out) if isinstance(out, Mapping) else {}
        except Exception:
            return {}
    return {}


class ShadowOptionTradeStore:
    """
    Writes shadow-only option execution records.

    Safety constraints:
    - Writes ONLY to the Firestore collection named `shadowTradeHistory`.
    - Idempotent on document id: uses Firestore `create()` semantics and returns the
      existing doc on replay (restart-safe).
    """

    collection_name: str = "shadowTradeHistory"

    def __init__(self, *, db: Any | None = None) -> None:
        if db is None:
            # Lazy import to keep module importable in minimal test environments.
            from backend.persistence.firebase_client import get_firestore_client  # noqa: WPS433

            db = get_firestore_client()
        self._db = db

        try:
            from backend.persistence.firestore_retry import with_firestore_retry  # noqa: WPS433
        except Exception:  # pragma: no cover
            with_firestore_retry = None  # type: ignore[assignment]
        self._with_retry = with_firestore_retry

    def _retry(self, fn):  # noqa: ANN001
        if callable(self._with_retry):
            return self._with_retry(fn)
        return fn()

    def create_simulated_once(
        self,
        *,
        doc_id: str,
        intent_id: UUID,
        option_symbol: str,
        contracts: int,
        side: str,
        reason: str,
        metadata_snapshot: Mapping[str, Any] | None,
        now_utc: datetime | None = None,
    ) -> Tuple[dict[str, Any], bool]:
        """
        Create a shadow option execution record once.

        Returns:
            (record, created):
              - created=True if we wrote a new document
              - created=False if the document already existed (replay)
        """
        ts = now_utc or _utc_now()
        doc_id_s = str(doc_id).strip()
        if not doc_id_s:
            raise ValueError("doc_id must be non-empty")

        record: dict[str, Any] = {
            "intent_id": str(intent_id),
            "option_symbol": str(option_symbol),
            "contracts": int(contracts),
            "side": str(side),
            "timestamp": (firestore.SERVER_TIMESTAMP if firestore is not None else ts),
            "timestamp_iso": ts.isoformat(),
            "status": "simulated",
            "reason": str(reason),
            "metadata_snapshot": _as_dict(metadata_snapshot),
        }

        ref = self._db.collection(self.collection_name).document(doc_id_s)

        try:
            self._retry(lambda: ref.create(record))
            return record, True
        except Exception as e:  # noqa: BLE001
            already_exists = False
            if gexc is not None:
                already_exists = isinstance(e, getattr(gexc, "AlreadyExists"))
            # In hermetic tests we may not have google exceptions; tolerate common patterns.
            if (not already_exists) and (e.__class__.__name__ in {"AlreadyExists", "Conflict"}):
                already_exists = True

            if not already_exists:
                raise

            snap = self._retry(lambda: ref.get())
            if getattr(snap, "exists", False):
                try:
                    existing = snap.to_dict() or {}
                except Exception:  # pragma: no cover
                    existing = {}
                return (existing if isinstance(existing, dict) else record), False
            return record, False


__all__ = ["ShadowOptionTradeStore"]

