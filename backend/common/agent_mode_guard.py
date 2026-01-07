"""
Runtime safety guard: refuse to start when AGENT_MODE=EXECUTE.

Defense-in-depth requirement:
- Container startup MUST fail closed if AGENT_MODE is missing/empty/invalid.
- Allowed modes: OFF, OBSERVE, EVAL, PAPER
- Forbidden mode: EXECUTE (hard stop)

This guard is intentionally lightweight and side-effect free so it can be invoked
at the very top of any entrypoint (including FastAPI startup hooks).
"""

from __future__ import annotations

import os
import sys
from typing import Final

AGENT_MODE_ENV: Final[str] = "AGENT_MODE"
ALLOWED_AGENT_MODES: Final[set[str]] = {"OFF", "OBSERVE", "EVAL", "PAPER"}
FORBIDDEN_MODE: Final[str] = "EXECUTE"
_GUARD_RAN_ENV: Final[str] = "_AGENT_MODE_GUARD_RAN"


def _die(msg: str, *, code: int) -> "None":
    print(msg, file=sys.stderr, flush=True)
    raise SystemExit(code)


def enforce_agent_mode_guard(*, env_var: str = AGENT_MODE_ENV) -> str:
    """
    Enforce runtime agent mode policy.

    Returns the normalized mode (uppercased) if allowed, otherwise exits.
    """
    # Idempotent: if multiple entrypoints/modules call the guard, only the first
    # invocation emits the canonical startup line.
    if os.getenv(_GUARD_RAN_ENV) == "1":
        raw = os.getenv(env_var)
        return (str(raw).strip().upper() if raw is not None else "")

    raw = os.getenv(env_var)
    if raw is None or str(raw).strip() == "":
        _die(
            f"AGENT_MODE_GUARD: missing required env var {env_var}; refusing to start (fail-closed)",
            code=11,
        )

    mode = str(raw).strip().upper()
    if mode == FORBIDDEN_MODE:
        _die(
            "AGENT_MODE_GUARD: AGENT_MODE=EXECUTE is forbidden; refusing to start",
            code=12,
        )

    if mode not in ALLOWED_AGENT_MODES:
        _die(
            f"AGENT_MODE_GUARD: invalid AGENT_MODE={mode!r} (allowed={sorted(ALLOWED_AGENT_MODES)}); refusing to start",
            code=13,
        )

    # Canonical startup line (single line, stable format).
    print(f"AGENT_STARTUP: mode={mode} execution_enabled=false", flush=True)
    os.environ[_GUARD_RAN_ENV] = "1"
    return mode


def main() -> None:
    enforce_agent_mode_guard()


if __name__ == "__main__":
    main()

