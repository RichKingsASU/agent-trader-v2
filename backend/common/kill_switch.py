from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from backend.common.runtime_execution_prevention import fatal_if_execution_reached

TRUTHY = {"1", "true", "yes", "on"}

# Standardized kill switch name (preferred)
KILL_SWITCH_ENV = "EXECUTION_HALTED"

# Optional: point to a file whose contents are truthy/falsey.
# This is ideal for Kubernetes ConfigMap volume mounts (updates propagate without restart).
KILL_SWITCH_FILE_ENV = "EXECUTION_HALTED_FILE"

# Back-compat (deprecated)
LEGACY_KILL_SWITCH_ENV = "EXEC_KILL_SWITCH"
LEGACY_KILL_SWITCH_FILE_ENV = "EXEC_KILL_SWITCH_FILE"


class ExecutionHaltedError(RuntimeError):
    """
    Raised when execution/trading is halted by the global kill switch.
    """


def _is_truthy(value: object | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in TRUTHY


def _read_first_line(path: str) -> str:
    # Keep it tiny and safe: read only a small prefix.
    p = Path(path)
    data = p.read_text(encoding="utf-8", errors="ignore")
    return (data.splitlines()[0] if data else "").strip()


def get_kill_switch_state() -> Tuple[bool, Optional[str]]:
    """
    Returns (enabled, source).

    Source values:
    - "env:EXECUTION_HALTED"
    - "env:EXEC_KILL_SWITCH" (deprecated)
    - "file:<path>" (from EXECUTION_HALTED_FILE / EXEC_KILL_SWITCH_FILE)
    """
    if _is_truthy(os.getenv(KILL_SWITCH_ENV)):
        return True, f"env:{KILL_SWITCH_ENV}"
    if _is_truthy(os.getenv(LEGACY_KILL_SWITCH_ENV)):
        return True, f"env:{LEGACY_KILL_SWITCH_ENV}"

    file_path = (os.getenv(KILL_SWITCH_FILE_ENV) or os.getenv(LEGACY_KILL_SWITCH_FILE_ENV) or "").strip()
    if file_path:
        try:
            if _is_truthy(_read_first_line(file_path)):
                return True, f"file:{file_path}"
        except Exception:
            # Fail-safe: unreadable file => do not halt (env var still halts).
            return False, None

    return False, None


def is_kill_switch_enabled() -> bool:
    enabled, _ = get_kill_switch_state()
    return enabled


def require_live_mode(*, operation: str = "trading") -> None:
    """
    Execution agents should call this immediately before any broker-side action.
    """
    enabled, source = get_kill_switch_state()
    if enabled:
        # Fail-closed at the absolute execution boundary.
        # This is intentionally fatal: if a codepath is attempting broker-side activity while the
        # global kill-switch is enabled, we must hard-stop before any network/broker calls.
        fatal_if_execution_reached(
            operation=f"kill_switch:{operation}",
            explicit_message=(
                f"Execution halted via {source or 'kill switch'}. Refusing {operation}. "
                f"Disable by setting {KILL_SWITCH_ENV}=0 (or updating {KILL_SWITCH_FILE_ENV})."
            ),
            context={"kill_switch_source": source, "operation": operation},
        )

