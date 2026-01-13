from __future__ import annotations

import logging
import random
import signal
import threading
import time
from typing import Callable, TypeVar

try:
    from google.api_core import exceptions as gexc  # type: ignore
except Exception:  # pragma: no cover
    # Local/unit-test environments may not have google libs installed.
    gexc = None  # type: ignore[assignment]

T = TypeVar("T")
logger = logging.getLogger(__name__)
_SHUTDOWN_EVENT = threading.Event()
_SHUTDOWN_HANDLERS_INSTALLED = False


def _install_shutdown_handlers_once() -> None:
    global _SHUTDOWN_HANDLERS_INSTALLED
    if _SHUTDOWN_HANDLERS_INSTALLED:
        return
    if threading.current_thread() is not threading.main_thread():
        return
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            prev = signal.getsignal(sig)

            def _handler(signum, frame, _prev=prev) -> None:  # type: ignore[no-untyped-def]
                _SHUTDOWN_EVENT.set()
                try:
                    if callable(_prev):
                        _prev(signum, frame)
                except Exception:
                    pass

            signal.signal(sig, _handler)
        _SHUTDOWN_HANDLERS_INSTALLED = True
    except Exception:
        return

if gexc is None:  # pragma: no cover
    _TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = ()
else:
    _TRANSIENT_EXCEPTIONS = (
        gexc.Aborted,
        gexc.DeadlineExceeded,
        gexc.InternalServerError,
        gexc.ResourceExhausted,
        gexc.ServiceUnavailable,
        gexc.TooManyRequests,
    )


def with_firestore_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int = 6,
    base_delay_s: float = 0.2,
    max_delay_s: float = 5.0,
) -> T:
    """
    Retry transient Firestore errors with exponential backoff + full jitter.

    Intended for Firestore write operations (set/create/update/batch.commit).
    """
    _install_shutdown_handlers_once()
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as e:
            is_transient = isinstance(e, _TRANSIENT_EXCEPTIONS)
            if (not is_transient) or attempt >= (max_attempts - 1):
                raise

            sleep_s = min(max_delay_s, base_delay_s * (2**attempt))
            logger.info("firestore_retry iteration=%d sleep_s=%.3f", attempt + 1, float(sleep_s))
            if _SHUTDOWN_EVENT.is_set():
                raise InterruptedError("shutdown requested") from e
            _SHUTDOWN_EVENT.wait(timeout=float(random.random() * float(sleep_s)))
            attempt += 1

