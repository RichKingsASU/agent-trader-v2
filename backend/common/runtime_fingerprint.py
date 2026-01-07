"""
Runtime fingerprint (startup truth).

Goal: every running container self-identifies exactly what code/image it is running.

This module is intentionally dependency-free and safe to import at the very top of
service entrypoints. It has no side effects beyond emitting one log block.
"""

from __future__ import annotations

import os
import sys
import threading
from typing import Optional

_LOG_ONCE_LOCK = threading.Lock()
_LOGGED = False


def _env(name: str, *, default: str = "unknown") -> str:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s else default


def _resolve_service_name(*, explicit: Optional[str] = None) -> str:
    """
    Resolve a stable service name from env vars, or fall back to the entry module name.
    """
    for key in ("SERVICE_NAME", "K_SERVICE", "WORKLOAD", "AGENT_NAME", "SERVICE"):
        v = os.getenv(key)
        if v and str(v).strip():
            return str(v).strip()

    if explicit and str(explicit).strip():
        return str(explicit).strip()

    try:
        import __main__  # noqa: PLC0415

        mod = getattr(__main__, "__package__", None) or getattr(__main__, "__name__", None)
        if mod and str(mod).strip() and str(mod).strip() != "__main__":
            return str(mod).strip()

        f = getattr(__main__, "__file__", None) or (sys.argv[0] if sys.argv else None)
        if f:
            base = os.path.basename(str(f))
            return base.rsplit(".", 1)[0] if "." in base else base
    except Exception:
        pass

    return "unknown"


def log_runtime_fingerprint(*, service: Optional[str] = None) -> None:
    """
    Log exactly once per process at startup.

    Output format (single structured block):
      RUNTIME_FINGERPRINT:
        service=<service>
        agent_mode=<AGENT_MODE>
        execution_enabled=false
        git_sha=<sha>
        image_tag=<tag>
    """
    global _LOGGED
    with _LOG_ONCE_LOCK:
        if _LOGGED:
            return
        _LOGGED = True

    svc = _resolve_service_name(explicit=service)
    agent_mode = _env("AGENT_MODE")
    git_sha = _env("GIT_SHA")
    image_tag = _env("IMAGE_TAG")

    block = (
        "RUNTIME_FINGERPRINT:\n"
        f"  service={svc}\n"
        f"  agent_mode={agent_mode}\n"
        "  execution_enabled=false\n"
        f"  git_sha={git_sha}\n"
        f"  image_tag={image_tag}"
    )

    # Print is the most reliable "logging-only" mechanism this early in startup
    # because many services configure logging later.
    try:
        print(block, flush=True)
    except Exception:
        # Never interfere with service startup.
        pass

