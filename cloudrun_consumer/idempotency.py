from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_message_once(
    *,
    txn: Any,
    dedupe_ref: Any,
    message_id: str,
    doc: Optional[dict[str, Any]] = None,
) -> Tuple[bool, Optional[dict[str, Any]]]:
    """
    Ensure at-least-once safety using a dedupe document keyed by `messageId`.

    Returns (is_first_time, existing_doc_dict_if_any).
    """
    if not message_id or not str(message_id).strip():
        # Without a stable message id, we cannot safely dedupe.
        return True, None

    snap = dedupe_ref.get(transaction=txn)
    if snap.exists:
        data = snap.to_dict() if snap is not None else None
        return False, data if isinstance(data, dict) else None

    try:
        from google.api_core.exceptions import AlreadyExists  # type: ignore
        from google.cloud import firestore  # type: ignore
    except Exception:
        AlreadyExists = None  # type: ignore[assignment]
        firestore = None  # type: ignore[assignment]

    try:
        # `create()` is a stronger signal than set/merge; it fails if doc exists.
        created_at = firestore.SERVER_TIMESTAMP if firestore is not None else None
        base: dict[str, Any] = {"createdAt": created_at, "messageId": str(message_id)}
        if isinstance(doc, dict) and doc:
            # Avoid writing explicit nulls into the dedupe doc.
            for k, v in doc.items():
                if v is not None:
                    base[k] = v
        txn.create(dedupe_ref, base)
    except Exception as e:
        if AlreadyExists is not None and isinstance(e, AlreadyExists):  # type: ignore[arg-type]
            # In case of race, treat as already-processed.
            return False, None
        raise

    return True, None


def ensure_doc_once(
    *,
    txn: Any,
    dedupe_ref: Any,
    key: str,
    doc: dict[str, Any],
) -> Tuple[bool, Optional[dict[str, Any]]]:
    """
    Transactionally ensure a dedupe doc exists exactly once.

    Returns (is_first_time, existing_doc_dict_if_any).

    Notes:
    - Uses `create()` (strong signal) so concurrent duplicates become a no-op.
    - Intended as a generic primitive for replay/consumer idempotency stores.
    """
    key_s = str(key or "").strip()
    if not key_s:
        return True, None

    snap = dedupe_ref.get(transaction=txn)
    if snap.exists:
        data = snap.to_dict() if snap is not None else None
        return False, data if isinstance(data, dict) else None

    try:
        from google.api_core.exceptions import AlreadyExists  # type: ignore
    except Exception:
        AlreadyExists = None  # type: ignore[assignment]

    try:
        txn.create(dedupe_ref, dict(doc))
    except Exception as e:
        if AlreadyExists is not None and isinstance(e, AlreadyExists):  # type: ignore[arg-type]
            return False, None
        raise

    return True, None

