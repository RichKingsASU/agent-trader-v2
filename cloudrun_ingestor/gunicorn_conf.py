"""
Gunicorn config: emit lifecycle logs for worker boot timing (logging-only).

Cloud Run requirement:
- detect Gunicorn worker boot time (post_fork -> post_worker_init)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any


#
# Runtime invariants for Cloud Run background-worker style service:
# - single worker + single thread to avoid duplicate ingestion loops
# - timeout 0 because the worker thread intentionally waits/sleeps between iterations
#
# Docker CMD also passes these flags explicitly; keeping them here ensures stability
# even if the container is started with only `--config gunicorn_conf.py`.
workers = 1
threads = 1
timeout = 0
# Cloud Run sends SIGTERM and provides ~10s for shutdown; keep Gunicorn's graceful
# shutdown window aligned so workers are not SIGKILLed by Gunicorn during orderly exit.
graceful_timeout = 10


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(event_type: str, **fields: Any) -> None:
    payload: dict[str, Any] = {
        "timestamp": _utc_ts(),
        "severity": "INFO",
        "event_type": str(event_type),
        "service": os.getenv("K_SERVICE", "cloudrun_ingestor"),
        "env": os.getenv("ENV", "unknown"),
        "pid": os.getpid(),
    }
    payload.update(fields)
    try:
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)
    except Exception:
        return


_MASTER_START_MONO: float | None = None


def on_starting(server) -> None:  # noqa: D401
    global _MASTER_START_MONO
    _MASTER_START_MONO = time.monotonic()
    _emit("gunicorn.master.starting", gunicorn_pid=int(getattr(server, "pid", 0) or 0))


def when_ready(server) -> None:  # noqa: D401
    started = _MASTER_START_MONO
    elapsed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0)) if started is not None else None
    _emit("gunicorn.master.ready", gunicorn_pid=int(getattr(server, "pid", 0) or 0), master_ready_ms=elapsed_ms)


def post_fork(server, worker) -> None:  # noqa: D401
    # Start of worker boot as soon as it's forked.
    try:
        worker._boot_start_mono = time.monotonic()  # type: ignore[attr-defined]
    except Exception:
        pass
    _emit(
        "gunicorn.worker.post_fork",
        worker_pid=int(getattr(worker, "pid", 0) or 0),
        worker_id=int(getattr(worker, "id", 0) or 0),
    )


def post_worker_init(worker) -> None:  # noqa: D401
    started = getattr(worker, "_boot_start_mono", None)
    elapsed_ms = int(max(0.0, (time.monotonic() - started) * 1000.0)) if isinstance(started, (int, float)) else None
    _emit(
        "gunicorn.worker.boot",
        worker_pid=int(getattr(worker, "pid", 0) or 0),
        worker_id=int(getattr(worker, "id", 0) or 0),
        worker_boot_ms=elapsed_ms,
    )

