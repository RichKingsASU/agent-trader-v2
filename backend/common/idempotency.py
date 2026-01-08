from __future__ import annotations

import uuid


_NAMESPACE = uuid.NAMESPACE_URL


def stable_uuid_from_key(*, key: str) -> uuid.UUID:
    """
    Derive a deterministic UUID from an arbitrary idempotency key.

    This is useful when downstream persistence expects UUID-like identifiers,
    but callers supply opaque idempotency tokens.
    """
    s = str(key or "").strip()
    if not s:
        raise ValueError("idempotency key must be non-empty")
    # uuid5 is stable/deterministic for a given (namespace, name).
    return uuid.uuid5(_NAMESPACE, s)

