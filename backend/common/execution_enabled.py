from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}


def is_execution_enabled() -> bool:
    """
    Repo-level authority gate for broker execution.

    Safety behavior:
    - Missing / empty => False (must be explicitly enabled)
    - Only truthy strings enable: 1/true/yes/on (case-insensitive)
    """
    raw = os.getenv("EXECUTION_ENABLED")
    return str(raw or "").strip().lower() in _TRUTHY


def require_execution_enabled(*, operation: str, context: Mapping[str, Any] | None = None) -> None:
    """
    Runtime safety guard: must be checked immediately before any broker-side action.

    If disabled:
    - Logs a clear error with context
    - Raises RuntimeError (fail-closed) before any network/broker side effects
    """
    if is_execution_enabled():
        return
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "intent_type": "execution_blocked",
        "operation": str(operation),
        "reason": "EXECUTION_ENABLED=false",
        "context": dict(context or {}),
    }
    logger.error("BLOCKED: execution disabled. %s", json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    raise RuntimeError(f"Execution disabled: refusing {operation}. Set EXECUTION_ENABLED=true to allow broker actions.")

