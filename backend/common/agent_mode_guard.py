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
from urllib.parse import urlparse

_ALLOWED = {"OFF", "OBSERVE", "EVAL", "PAPER"}
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
_ALLOW_LIVE_TRADING_CODE_CHANGE = False


def _emit_fatal(msg: str) -> None:
    """
    Emit a stable fatal message to stderr (and flush best-effort).

    This complements logging so container logs + pytest capsys can assert
    explicit failure reasons.
    """
    try:
        sys.stderr.write(msg + "\n")
        try:
            sys.stderr.flush()
        except Exception:
            pass
    except Exception:
        pass


def _read_alpaca_base_url_any() -> str:
    """
    Read APCA_API_BASE_URL (canonical) or any documented alias.

    NOTE: This guard does not require Alpaca usage globally; it only validates
    consistency if a base URL is present.
    """
    v = os.getenv("APCA_API_BASE_URL") or ""
    if not v:
        v = os.getenv("ALPACA_TRADING_HOST") or ""
    if not v:
        v = os.getenv("ALPACA_API_BASE_URL") or ""
    if not v:
        v = os.getenv("ALPACA_API_URL") or ""
    return str(v).strip()


def _alpaca_base_url_kind(url: str) -> str:
    """
    Classify Alpaca base url as 'paper', 'live', or 'other'.
    """
    raw = (url or "").strip()
    if not raw:
        return "other"
    parse_target = raw
    if "://" not in parse_target:
        # Be lenient for host-only configs.
        parse_target = "https://" + parse_target
    try:
        host = (urlparse(parse_target).hostname or "").lower()
    except Exception:
        host = ""
    if host == "paper-api.alpaca.markets":
        return "paper"
    if host == "api.alpaca.markets":
        return "live"
    return "other"


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
        msg = (
            "FATAL: AGENT_MODE is missing/empty. "
            f"Allowed: {sorted(_ALLOWED)} (and EXECUTE is forbidden)."
        )
        _emit_fatal(msg)
        logger.error("%s", msg)
        raise SystemExit(1)

    if mode == "EXECUTE":
        msg = "FATAL: AGENT_MODE=EXECUTE is forbidden; refusing to start."
        _emit_fatal(msg)
        logger.critical("%s", msg)
        raise SystemExit(12)

    if mode not in _ALLOWED:
        msg = f"FATAL: Invalid AGENT_MODE={raw!r}. Allowed: {sorted(_ALLOWED)} (and EXECUTE is forbidden)."
        _emit_fatal(msg)
        logger.error("%s", msg)
        raise SystemExit(1)

    # --- Paper trading hard lock (non-bypassable by env/config alone) ---
    raw_tm = os.getenv("TRADING_MODE")
    trading_mode = str(raw_tm).strip().lower() if raw_tm is not None else ""
    if raw_tm is None or trading_mode == "":
        # Print a stable, explicit message (in addition to logging) for container logs / CI.
        msg = (
            "FATAL: TRADING_MODE is missing/empty. This repo is paper-trading locked. "
            "Set TRADING_MODE=paper to start."
        )
        _emit_fatal(msg)
        logger.critical("%s", msg)
        raise SystemExit(13)

    # --- Canonical env var contract: TRADING_MODE <-> APCA_API_BASE_URL pairing ---
    # Fail fast with an explicit mismatch reason before the broader paper-only lock.
    alpaca_url = _read_alpaca_base_url_any()
    if alpaca_url:
        kind = _alpaca_base_url_kind(alpaca_url)
        if trading_mode == "paper" and kind == "live":
            msg = (
                "FATAL: TRADING_MODE=paper requires a paper Alpaca base URL "
                "(APCA_API_BASE_URL host must be paper-api.alpaca.markets). "
                f"Got APCA_API_BASE_URL={alpaca_url!r}."
            )
            _emit_fatal(msg)
            logger.critical("%s", msg)
            raise SystemExit(13)
        if trading_mode == "live" and kind == "paper":
            msg = (
                "FATAL: TRADING_MODE=live requires a live Alpaca base URL "
                "(APCA_API_BASE_URL host must be api.alpaca.markets). "
                f"Got APCA_API_BASE_URL={alpaca_url!r}."
            )
            _emit_fatal(msg)
            logger.critical("%s", msg)
            raise SystemExit(13)

    if trading_mode != "paper":
        if not _ALLOW_LIVE_TRADING_CODE_CHANGE:
            msg = (
                f"FATAL: TRADING_MODE must be 'paper' (paper-trading hard lock). "
                f"Got TRADING_MODE={raw_tm!r}. "
                "Live trading is code-disabled; enabling it requires changing "
                "`backend/common/agent_mode_guard.py` (_ALLOW_LIVE_TRADING_CODE_CHANGE) "
                "and adding an explicit execution confirmation mechanism."
            )
            _emit_fatal(msg)
            logger.critical("%s", msg)
            raise SystemExit(13)

    return mode

