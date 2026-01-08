from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class WsFailureInfo:
    """
    Normalized classification for WebSocket connection failures.

    Categories:
    - auth_failure: unrecoverable (bad/expired credentials / forbidden)
    - rate_limited: server-side throttling (HTTP 429)
    - transient: network/server hiccup; safe to retry with backoff
    """

    category: str
    http_status: int | None
    reason: str

    def is_auth_failure(self) -> bool:
        return self.category == "auth_failure"

    def is_rate_limited(self) -> bool:
        return self.category == "rate_limited"


class UnrecoverableAuthError(RuntimeError):
    """
    Raised when WS auth failure is detected and retries must stop.
    """


_STATUS_RE = re.compile(r"(?<!\d)(401|403|429)(?!\d)")


def _extract_http_status(exc: BaseException) -> int | None:
    """
    Best-effort extract of HTTP status code from common WS libraries.
    """
    for attr in ("status_code", "code", "status"):
        v = getattr(exc, attr, None)
        if v is None:
            continue
        # websockets sometimes uses an int, or an enum-like object with `.value`
        try:
            if isinstance(v, int):
                return v
            vv = getattr(v, "value", None)
            if isinstance(vv, int):
                return vv
        except Exception:
            continue

    # Some exceptions only embed the status in the string representation.
    try:
        msg = str(exc)
    except Exception:
        msg = ""
    m = _STATUS_RE.search(msg)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def classify_ws_failure(exc: BaseException) -> WsFailureInfo:
    """
    Classify a WebSocket failure into {auth_failure, rate_limited, transient}.

    This intentionally uses conservative heuristics:
    - Any explicit HTTP 401/403 => auth_failure (unrecoverable)
    - Any explicit HTTP 429 => rate_limited
    - Keyword matching on the exception string as a fallback
    """
    status = _extract_http_status(exc)
    try:
        msg = str(exc).lower()
    except Exception:
        msg = ""

    if status in (401, 403):
        return WsFailureInfo(category="auth_failure", http_status=status, reason="http_status")
    if status == 429:
        return WsFailureInfo(category="rate_limited", http_status=status, reason="http_status")

    # Fallback keyword heuristics (covers libraries that don't expose status code cleanly).
    if any(k in msg for k in ("auth failed", "authentication failed", "unauthorized", "forbidden", "invalid api key")):
        return WsFailureInfo(category="auth_failure", http_status=status, reason="message_match")
    if any(k in msg for k in ("too many requests", "rate limit", "ratelimit", "429")):
        return WsFailureInfo(category="rate_limited", http_status=status, reason="message_match")

    return WsFailureInfo(category="transient", http_status=status, reason="default")


def ensure_retry_allowed(*, attempt: int, max_attempts: int) -> None:
    """
    Guard against infinite/busy reconnect loops.
    """
    if max_attempts <= 0:
        raise RuntimeError("max_attempts must be > 0")
    # `attempt` is 1-based in our backoff implementation (first failure => attempt=1).
    # Allow exactly `max_attempts` retry attempts; fail on attempt > max_attempts.
    if attempt > max_attempts:
        raise RuntimeError(f"max reconnect attempts exceeded (attempt={attempt} max_attempts={max_attempts})")

