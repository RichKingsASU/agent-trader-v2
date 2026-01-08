from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_message_once(
    *,
    txn: firestore.Transaction,
    dedupe_ref: firestore.DocumentReference,
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
        # `create()` is a stronger signal than set/merge; it fails if doc exists.
        txn.create(dedupe_ref, {"createdAt": firestore.SERVER_TIMESTAMP, "messageId": str(message_id)})
    except AlreadyExists:
        # In case of race, treat as already-processed.
        return False, None

    return True, None

