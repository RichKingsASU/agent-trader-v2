from __future__ import annotations

from typing import Any


_SUSPECT_SUBSTRINGS = (
    "key",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "bearer",
)


def _is_secret_key(k: Any) -> bool:
    try:
        s = str(k).strip().lower()
    except Exception:
        return False
    return any(sub in s for sub in _SUSPECT_SUBSTRINGS)


def redact_value(v: Any) -> Any:
    # Keep structure, redact content.
    if v is None:
        return None
    if isinstance(v, (bytes, bytearray)):
        return "[REDACTED_BYTES]"
    if isinstance(v, str):
        return "[REDACTED]"
    return "[REDACTED]"


def redact_dict(d: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively redact common secret-like keys.
    """
    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                if _is_secret_key(k):
                    out[str(k)] = redact_value(v)
                else:
                    out[str(k)] = _walk(v)
            return out
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        if isinstance(obj, tuple):
            return [_walk(x) for x in obj]
        return obj

    if not isinstance(d, dict):
        return {}
    return _walk(d)

