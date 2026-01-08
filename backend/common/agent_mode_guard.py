"""
Runtime safety guard for agent mode.

Goal: hard-prevent any runtime from starting with AGENT_MODE=EXECUTE.
"""

from __future__ import annotations

import logging
import os
import sys

_ALLOWED = {"OFF", "OBSERVE", "EVAL", "PAPER"}
_logged_startup = False


def enforce_agent_mode_guard() -> str:
    """
    Enforce that AGENT_MODE is explicitly set and is NOT EXECUTE.

    Rules:
    - Allowed: OFF, OBSERVE, EVAL, PAPER
    - Missing/empty/unknown => exit(1)
    - EXECUTE => exit(12)

    Also emits exactly one startup log line:
      "AGENT_STARTUP: mode=<MODE> execution_enabled=false"
    """
    global _logged_startup

    raw = os.getenv("AGENT_MODE")
    mode = str(raw).strip().upper() if raw is not None else ""
    mode_for_log = mode or "MISSING"

    if not _logged_startup:
        # This line is intentionally stable and easy to grep in container logs.
        service = (
            (os.getenv("SERVICE_NAME") or "").strip()
            or (os.getenv("K_SERVICE") or "").strip()
            or (os.getenv("AGENT_NAME") or "").strip()
            or "unknown"
        )
        env = (
            (os.getenv("ENVIRONMENT") or "").strip()
            or (os.getenv("ENV") or "").strip()
            or (os.getenv("APP_ENV") or "").strip()
            or (os.getenv("DEPLOY_ENV") or "").strip()
            or "unknown"
        )
        try:
            sys.stdout.write(
                f"AGENT_STARTUP: mode={mode_for_log} execution_enabled=false service={service} env={env}\n"
            )
            try:
                sys.stdout.flush()
            except Exception:
                pass
        except Exception:
            pass
        _logged_startup = True

    logger = logging.getLogger(__name__)

    if raw is None or mode == "":
        logger.error("AGENT_MODE missing; refusing to start")
        raise SystemExit(1)

    if mode == "EXECUTE":
        logger.critical("AGENT_MODE=EXECUTE is forbidden; refusing to start")
        raise SystemExit(12)

    if mode not in _ALLOWED:
        logger.error("AGENT_MODE=%s not allowed (allowed=%s); refusing to start", mode, sorted(_ALLOWED))
        raise SystemExit(1)

    return mode

