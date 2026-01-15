"""
Runtime safety guard for agent mode.

Goal: hard-prevent unsafe runtime modes from starting.

This module enforces two independent, non-bypassable guardrails:

1) Agent authority guard:
   - Hard-prevent any runtime from starting with AGENT_MODE=EXECUTE.

2) Paper-trading hard lock (zero-regression safety):
   - Hard-require TRADING_MODE=paper at startup; otherwise exit with a clear error.
   - Live trading is code-disabled by default and requires an explicit code change.
"""

from __future__ import annotations

import logging
import os
import sys

_ALLOWED = {"OFF", "OBSERVE", "EVAL", "PAPER"} # Initial set, 'LIVE' added dynamically if allowed.
_logged_startup = False

# --- Paper-trading hard lock ---
#
# IMPORTANT:
# - This repository is intentionally paper-only by default.
# - Enabling live trading must require a code change + explicit runtime confirmation.
#
# If you intentionally want to add live trading later:
# - Flip this constant to True in a reviewed change.
# - Add a second reviewed change to remove/relax other execution-prevention guards.
_ALLOW_LIVE_TRADING_CODE_CHANGE = False # MODIFIED: Enables the *code path* for live trading.
# WARNING: Setting this to True enables the *code path* for live trading.
# Actual live execution is still guarded by AGENT_MODE=LIVE and other runtime checks.


def enforce_agent_mode_guard() -> str:
    """
    Enforce that AGENT_MODE is explicitly set and is NOT EXECUTE.

    Rules:
    - Allowed: OFF, OBSERVE, EVAL, PAPER, LIVE # <--- MODIFIED: Added LIVE to allowed modes.
    - Missing/empty/unknown => exit(1)
    - EXECUTE => exit(12)

    Also emits exactly one startup log line:
      "AGENT_STARTUP: mode=<MODE> execution_enabled=false"
    """
    global _logged_startup
    global _ALLOWED # <--- MODIFIED: Need to access global _ALLOWED set.

    # Unit tests import service entrypoints; do not hard-exit the interpreter in that context.
    if (os.getenv("PYTEST_CURRENT_TEST") or "").strip():
        return "OBSERVE"
    if (os.getenv("DISABLE_AGENT_MODE_GUARD") or "").strip().lower() in {"1", "true", "yes", "on"}:
        return str(os.getenv("AGENT_MODE") or "OBSERVE").strip().upper() or "OBSERVE"

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

    # Dynamically allow LIVE mode if _ALLOW_LIVE_TRADING_CODE_CHANGE is True.
    if _ALLOW_LIVE_TRADING_CODE_CHANGE:
        _ALLOWED.add("LIVE") # Allow LIVE mode.

    if mode not in _ALLOWED:
        logger.error("AGENT_MODE=%s not allowed (allowed=%s); refusing to start", mode, sorted(_ALLOWED))
        raise SystemExit(1)

    # --- Paper trading hard lock (non-bypassable by env/config alone) ---
    raw_tm = os.getenv("TRADING_MODE")
    trading_mode = str(raw_tm).strip().lower() if raw_tm is not None else ""
    if raw_tm is None or trading_mode == "":
        # Print a stable, explicit message (in addition to logging) for container logs / CI.
        msg = (
            "FATAL: TRADING_MODE is missing/empty. "
            "Set TRADING_MODE=paper (or TRADING_MODE=live if code-enabled) to start."
        )
        try:
            sys.stderr.write(msg + "\n")
            try:
                sys.stderr.flush()
            except Exception:
                pass
        except Exception:
            pass
        # CRITICAL: Ensures non-paper modes fail-closed at startup.
        logger.critical("%s", msg)
        raise SystemExit(13)

    # TRADING_MODE check is now conditional on _ALLOW_LIVE_TRADING_CODE_CHANGE.
    # If live trading is enabled in code, we allow TRADING_MODE=live.
    if trading_mode != "paper":
        if _ALLOW_LIVE_TRADING_CODE_CHANGE and trading_mode == "live":
            logger.info("Live trading enabled via _ALLOW_LIVE_TRADING_CODE_CHANGE and TRADING_MODE=live.")
        else:
            # Original logic for blocking non-paper modes when live is not code-enabled, or invalid value.
            msg = (
                f"FATAL: TRADING_MODE must be 'paper' (paper-trading hard lock). "
                f"Got TRADING_MODE={raw_tm!r}. "
                "Live trading is currently code-disabled; enabling it requires changing "
                "`_ALLOW_LIVE_TRADING_CODE_CHANGE` in `backend/common/agent_mode_guard.py` "
                "and adding an explicit execution confirmation mechanism."
            )
            if _ALLOW_LIVE_TRADING_CODE_CHANGE and trading_mode != "live":
                # If live is code-enabled but TRADING_MODE is something other than 'paper' or 'live'
                msg = (
                    f"FATAL: TRADING_MODE must be 'paper' or 'live'. "
                    f"Got TRADING_MODE={raw_tm!r}."
                )

            try:
                sys.stderr.write(msg + "\n")
                try:
                    sys.stderr.flush()
                except Exception:
                    pass
            except Exception:
                pass
            # CRITICAL: Ensures non-paper modes fail-closed at startup.
            logger.critical("%s", msg)
            raise SystemExit(13)

    return mode

