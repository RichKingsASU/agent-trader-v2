from __future__ import annotations

import os
from enum import Enum


class AgentMode(str, Enum):
    """
    Global trading authority mode.

    Values:
    - DISABLED: trading fully disabled (default)
    - WARMUP: strategies may run, but MUST NOT trade
    - LIVE: trading allowed (only execution-capable runtime should ever set this)
    - HALTED: emergency stop; MUST refuse trading regardless of other flags
    """

    DISABLED = "DISABLED"
    WARMUP = "WARMUP"
    # Back-compat aliases used by several modules/tests.
    OBSERVE = "OBSERVE"
    PAPER = "PAPER"
    LIVE = "LIVE"
    HALTED = "HALTED"


class AgentModeError(RuntimeError):
    """
    Raised when a trading action is attempted outside LIVE mode.
    """


def get_agent_mode() -> AgentMode:
    """
    Parse AGENT_MODE from environment (case-insensitive).

    Safety behavior:
    - Missing/empty/unknown values => DISABLED
    """
    raw = os.getenv("AGENT_MODE")
    if raw is None:
        return AgentMode.DISABLED
    v = str(raw).strip().upper()
    if not v:
        return AgentMode.DISABLED
    try:
        return AgentMode(v)
    except Exception:
        return AgentMode.DISABLED


def require_live_mode(*, action: str = "place_order") -> None:
    """
    Enforce that trading can only happen when AGENT_MODE=LIVE.

    This is an authority boundary guard: if a runtime is not explicitly authorized
    for LIVE trading, it must fail-closed.
    """
    mode = get_agent_mode()
    if mode == AgentMode.LIVE:
        return
    if mode == AgentMode.HALTED:
        raise AgentModeError(
            f"Refusing to {action}: AGENT_MODE=HALTED (emergency stop)."
        )
    raise AgentModeError(
        f"Refusing to {action}: AGENT_MODE={mode.value} (must be LIVE to trade)."
    )

