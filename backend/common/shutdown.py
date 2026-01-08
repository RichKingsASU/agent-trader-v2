from __future__ import annotations

"""
Thread-friendly graceful shutdown utilities.

Why this exists:
- Many services run long-lived loops (polling, retries, backoff, heartbeats).
- `time.sleep()` is not interruptible by our own shutdown signals, which can delay
  exit past Cloud Run / K8s grace periods.

This module provides:
- A shared `threading.Event` that is set on SIGTERM/SIGINT (best-effort).
- An interruptible wait helper (`wait_or_shutdown`) used in place of `time.sleep`.

Important:
- We *chain* any previous signal handlers so frameworks (gunicorn/uvicorn/etc.)
  keep their expected behavior.
- If the previous handler was SIG_DFL, we emulate default termination via
  `SystemExit(128+signal)` so `atexit` handlers can still run.
"""

import signal
import threading
from types import FrameType
from typing import Any, Callable

SHUTDOWN_EVENT = threading.Event()

_INSTALLED = False
_LOCK = threading.Lock()


def request_shutdown(*, reason: str | None = None) -> None:
    """
    Programmatically request shutdown (idempotent).
    """
    # `reason` is currently informational only (kept for call sites).
    _ = reason
    try:
        SHUTDOWN_EVENT.set()
    except Exception:
        pass


def wait_or_shutdown(timeout_s: float) -> bool:
    """
    Interruptible wait.

    Returns:
    - True if shutdown was requested (event set)
    - False if the timeout elapsed without a shutdown request
    """
    try:
        return bool(SHUTDOWN_EVENT.wait(timeout=max(0.0, float(timeout_s))))
    except Exception:
        # If Event.wait fails for any reason, fall back to "no shutdown".
        return bool(SHUTDOWN_EVENT.is_set())


def _wrap_handler(prev: Any) -> Callable[[int, FrameType | None], Any]:
    def _handler(signum: int, frame: FrameType | None) -> Any:
        request_shutdown(reason=f"signal:{signum}")

        # Chain previous behavior (frameworks may rely on this).
        try:
            if prev == signal.SIG_IGN:
                return None
            if prev == signal.SIG_DFL:
                raise SystemExit(128 + int(signum))
            if callable(prev):
                return prev(signum, frame)
        except SystemExit:
            raise
        except Exception:
            # Never block shutdown due to handler issues.
            return None
        return None

    return _handler


def install_signal_handlers_once() -> None:
    """
    Best-effort SIGTERM/SIGINT → set `SHUTDOWN_EVENT`.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    # Signal handlers can only be installed reliably from the main thread.
    if threading.current_thread() is not threading.main_thread():
        return
    with _LOCK:
        if _INSTALLED:
            return
        try:
            for s in (signal.SIGTERM, signal.SIGINT):
                prev = signal.getsignal(s)
                signal.signal(s, _wrap_handler(prev))
            _INSTALLED = True
        except Exception:
            # Never fail import/startup due to signal limitations.
            return

