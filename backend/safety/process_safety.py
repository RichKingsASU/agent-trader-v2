from __future__ import annotations

import asyncio
import json
import os
import platform
import signal
import socket
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Sequence

from backend.safety.startup_validation import validate_agent_mode_or_exit, validate_required_env_or_exit


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit_json(*, service: str, intent_type: str, severity: str = "INFO", **fields: Any) -> None:
    payload = {
        "ts": _utc_now_iso(),
        "service": service,
        "env": (os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("APP_ENV") or os.getenv("DEPLOY_ENV") or "unknown"),
        "intent_type": intent_type,
        "severity": str(severity).upper(),
        **fields,
    }
    try:
        sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        try:
            sys.stdout.flush()
        except Exception:
            pass
    except Exception:
        return


def startup_banner(*, service: str, intent: str, **extra: Any) -> None:
    """
    Emit a single, high-signal startup banner line.
    """
    _emit_json(
        service=service,
        intent_type="startup_banner",
        intent=intent,
        pid=os.getpid(),
        ppid=os.getppid(),
        hostname=socket.gethostname(),
        python_version=platform.python_version(),
        platform=f"{platform.system()} {platform.release()}",
        cwd=os.getcwd(),
        argv=list(sys.argv),
        **extra,
    )


def validate_startup_or_exit(
    *,
    service: str,
    allowed_agent_modes: set[str] | None = None,
    required_env: Iterable[str] = (),
) -> None:
    """
    Fail-fast validation for long-running daemons.
    """
    if allowed_agent_modes is not None:
        validate_agent_mode_or_exit(allowed=allowed_agent_modes)
    if required_env:
        validate_required_env_or_exit(required=required_env, intent_type="startup_validation_failed")
    _emit_json(service=service, intent_type="startup_validation", status="ok")


def validate_any_env_or_exit(*, service: str, any_of: Sequence[str]) -> None:
    """
    Fail-fast unless at least one env var in `any_of` is set to a non-empty value.
    """
    for k in any_of:
        v = os.getenv(k)
        if v is not None and str(v).strip() != "":
            return
    _emit_json(
        service=service,
        intent_type="startup_validation_failed",
        severity="ERROR",
        reason_codes=[f"any_of_missing:{'|'.join(any_of)}"],
        details={"any_of": list(any_of)},
    )
    raise SystemExit(2)


class AsyncShutdown:
    """
    Centralized SIGTERM/SIGINT handling for asyncio services.
    """

    def __init__(self, *, service: str) -> None:
        self.service = service
        self.stop_event = asyncio.Event()
        self._installed = False
        self._callbacks: list[Callable[[], Any]] = []

    def add_callback(self, cb: Callable[[], Any]) -> None:
        """
        Register a best-effort callback invoked exactly once at shutdown initiation.
        The callback may be sync or async; async callbacks are scheduled.
        """
        self._callbacks.append(cb)

    def request_stop(self, *, reason: str, signum: int | None = None) -> None:
        if self.stop_event.is_set():
            return
        _emit_json(
            service=self.service,
            intent_type="shutdown_initiated",
            reason=reason,
            signum=signum,
        )
        self.stop_event.set()
        for cb in self._callbacks:
            try:
                res = cb()
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                # Best-effort only.
                pass

    def install(self) -> None:
        if self._installed:
            return
        loop = asyncio.get_running_loop()

        def _handler(signum: int) -> None:
            _emit_json(service=self.service, intent_type="signal_received", signum=signum)
            self.request_stop(reason="signal", signum=signum)

        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(s, _handler, int(s))
            except NotImplementedError:
                signal.signal(s, lambda _sig, _frame: _handler(int(_sig)))

        self._installed = True


async def heartbeat_log_loop(
    *,
    service: str,
    stop_event: asyncio.Event,
    interval_s: float,
    details_fn: Callable[[], dict[str, Any]] | None = None,
) -> None:
    """
    Periodic heartbeat log until stop_event is set.
    """
    interval = max(1.0, float(interval_s))
    while not stop_event.is_set():
        details = {}
        try:
            details = (details_fn() if details_fn is not None else {}) or {}
        except Exception:
            details = {}
        _emit_json(service=service, intent_type="heartbeat", **details)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

