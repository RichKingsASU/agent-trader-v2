from __future__ import annotations

"""
Central shutdown gate for safe trading stoppage.

Goals:
- Provide a single, process-wide "shutdown requested" flag.
- Prevent *starting* new broker submissions during shutdown.
- Track in-flight broker submissions so shutdown can wait (briefly) for them to finish.

This is intentionally lightweight (stdlib only) and safe to import anywhere.
"""

import threading
import time
from dataclasses import dataclass
from typing import Optional


class ShutdownRequestedError(RuntimeError):
    """
    Raised when an operation is refused due to shutdown being requested.
    """


_SHUTDOWN_EVENT = threading.Event()
_STATE_LOCK = threading.Lock()
_INFLIGHT_COND = threading.Condition(_STATE_LOCK)
_INFLIGHT_SUBMISSIONS = 0
_SHUTDOWN_REASON: Optional[str] = None
_SHUTDOWN_REQUESTED_AT_MONO: Optional[float] = None


def request_shutdown(*, reason: str) -> None:
    """
    Idempotently request a process shutdown.
    """
    global _SHUTDOWN_REASON, _SHUTDOWN_REQUESTED_AT_MONO
    if _SHUTDOWN_EVENT.is_set():
        return
    with _STATE_LOCK:
        if _SHUTDOWN_EVENT.is_set():
            return
        _SHUTDOWN_REASON = str(reason).strip() or "shutdown_requested"
        _SHUTDOWN_REQUESTED_AT_MONO = time.monotonic()
        _SHUTDOWN_EVENT.set()
        _INFLIGHT_COND.notify_all()


def shutdown_requested() -> bool:
    return _SHUTDOWN_EVENT.is_set()


def shutdown_reason() -> Optional[str]:
    with _STATE_LOCK:
        return _SHUTDOWN_REASON


def check_not_shutting_down(*, operation: str) -> None:
    """
    Refuse an operation if shutdown has been requested.
    """
    if _SHUTDOWN_EVENT.is_set():
        raise ShutdownRequestedError(f"shutdown requested; refusing {operation}")


@dataclass(frozen=True)
class ShutdownGateStatus:
    shutdown_requested: bool
    shutdown_reason: Optional[str]
    inflight_submissions: int
    shutdown_requested_at_mono: Optional[float]


def status() -> ShutdownGateStatus:
    with _STATE_LOCK:
        return ShutdownGateStatus(
            shutdown_requested=_SHUTDOWN_EVENT.is_set(),
            shutdown_reason=_SHUTDOWN_REASON,
            inflight_submissions=int(_INFLIGHT_SUBMISSIONS),
            shutdown_requested_at_mono=_SHUTDOWN_REQUESTED_AT_MONO,
        )


class OrderSubmissionGuard:
    """
    Context manager guarding broker submissions.

    - Blocks starting submissions after shutdown is requested.
    - Increments an in-flight counter while the submission is in progress.
    """

    def __init__(self, *, operation: str = "broker submission") -> None:
        self._operation = str(operation).strip() or "broker submission"
        self._entered = False

    def __enter__(self) -> "OrderSubmissionGuard":
        check_not_shutting_down(operation=self._operation)
        global _INFLIGHT_SUBMISSIONS
        with _STATE_LOCK:
            if _SHUTDOWN_EVENT.is_set():
                raise ShutdownRequestedError(f"shutdown requested; refusing {self._operation}")
            _INFLIGHT_SUBMISSIONS += 1
            self._entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        global _INFLIGHT_SUBMISSIONS
        if not self._entered:
            return
        with _STATE_LOCK:
            _INFLIGHT_SUBMISSIONS = max(0, int(_INFLIGHT_SUBMISSIONS) - 1)
            _INFLIGHT_COND.notify_all()


def wait_for_inflight_zero(*, timeout_s: float) -> bool:
    """
    Best-effort wait for in-flight submissions to drain to zero.

    Returns True if drained, False if timed out.
    """
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    with _STATE_LOCK:
        while _INFLIGHT_SUBMISSIONS > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _INFLIGHT_COND.wait(timeout=remaining)
        return True

