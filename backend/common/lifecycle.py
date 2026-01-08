"""
Container lifecycle logging:
- Log SIGTERM receipt (immediately, no delays).
- Log shutdown duration (ms) on process exit.
- Log exit reason (signal vs exception vs normal).

This module is designed to be safe to import very early (e.g., from `backend/__init__.py`)
and to coexist with frameworks that install their own signal handlers (uvicorn, gunicorn, etc.).
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from types import FrameType
from typing import Any, Callable

_INSTALLED = False

_PROCESS_PID = os.getpid()
_PROCESS_START_MONOTONIC = time.monotonic()

_shutdown_started_monotonic: float | None = None
_exit_reason: str | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _emit(event: str, **fields: Any) -> None:
    """
    Best-effort single-line JSON to stderr.
    We avoid depending on any logging configuration that may not exist yet.
    """
    payload = {
        "ts": _utc_now_iso(),
        "event": event,
        "pid": _PROCESS_PID,
        # Common container/service identifiers (best-effort).
        "service": os.getenv("K_SERVICE") or os.getenv("SERVICE_NAME") or None,
        "revision": os.getenv("K_REVISION") or None,
        **fields,
    }
    try:
        sys.stderr.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def _signal_name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except Exception:
        return str(signum)


def _record_shutdown_start(reason: str) -> None:
    global _shutdown_started_monotonic, _exit_reason
    if _shutdown_started_monotonic is None:
        _shutdown_started_monotonic = time.monotonic()
    if _exit_reason is None:
        _exit_reason = reason


def _wrap_handler(signum: int, handler: Any) -> Callable[[int, FrameType | None], Any]:
    """
    Wrap a signal handler so we log receipt first, then delegate to the original handler.

    Important: Frameworks may install/replace handlers after import; we patch `signal.signal`
    so future registrations for SIGTERM/SIGINT get wrapped too.
    """

    def _wrapped(sig: int, frame: FrameType | None) -> Any:
        name = _signal_name(sig)
        _record_shutdown_start(f"signal:{name}")
        _emit("sigterm_received" if sig == signal.SIGTERM else "signal_received", signal=name)

        if handler == signal.SIG_IGN:
            return None
        if handler == signal.SIG_DFL:
            # Exit via SystemExit so our atexit hook can record shutdown duration.
            raise SystemExit(128 + sig)

        if callable(handler):
            return handler(sig, frame)
        return None

    return _wrapped


def install_container_lifecycle_logging() -> None:
    """
    Idempotently install lifecycle logging hooks.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Patch signal.signal so later handler installs (uvicorn/gunicorn/etc.) keep our receipt log.
    try:
        _orig_signal = signal.signal

        def _signal(signum: int, handler: Any):  # type: ignore[override]
            if signum in (signal.SIGTERM, signal.SIGINT):
                return _orig_signal(signum, _wrap_handler(signum, handler))
            return _orig_signal(signum, handler)

        signal.signal = _signal  # type: ignore[assignment]

        # Also wrap the current handlers to catch signals even if nobody replaces them.
        for s in (signal.SIGTERM, signal.SIGINT):
            try:
                current = signal.getsignal(s)
                _orig_signal(s, _wrap_handler(s, current))
            except Exception:
                pass
    except Exception:
        # Never fail startup due to lifecycle hooks.
        pass

    # Record unhandled exceptions as an exit reason.
    try:
        orig = sys.excepthook

        def _hook(exc_type, exc, tb):  # type: ignore[override]
            try:
                _record_shutdown_start(f"exception:{getattr(exc_type, '__name__', str(exc_type))}")
                _emit(
                    "process_exception",
                    exc_type=getattr(exc_type, "__name__", str(exc_type)),
                    message=str(exc),
                )
            except Exception:
                pass
            return orig(exc_type, exc, tb)

        sys.excepthook = _hook  # type: ignore[assignment]
    except Exception:
        pass

    # Emit shutdown duration + reason on process exit.
    @atexit.register
    def _on_exit() -> None:
        started = _shutdown_started_monotonic
        if started is None:
            started = time.monotonic()
        shutdown_ms = int(max(0.0, (time.monotonic() - started) * 1000.0))
        uptime_ms = int(max(0.0, (time.monotonic() - _PROCESS_START_MONOTONIC) * 1000.0))
        reason = _exit_reason or "normal"
        _emit("process_exit", exit_reason=reason, shutdown_duration_ms=shutdown_ms, uptime_ms=uptime_ms)

