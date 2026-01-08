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
) -> Tuple[bool, Optional[dict[str, Any]]]:
    """
    Ensure at-least-once safety using `ops_dedupe/{messageId}`.

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
        txn.create(dedupe_ref, {"createdAt": created_at, "messageId": str(message_id)})
    except Exception as e:
        if AlreadyExists is not None and isinstance(e, AlreadyExists):  # type: ignore[arg-type]
            # In case of race, treat as already-processed.
            return False, None
        raise

    return True, None

