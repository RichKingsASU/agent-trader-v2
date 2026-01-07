from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Mapping, NoReturn

logger = logging.getLogger(__name__)


class FatalExecutionPathError(RuntimeError):
    """
    Raised when a live-execution codepath is reached.

    This repo is safety-hardened so that *runtime order execution is impossible*
    even under misconfiguration. If you see this exception, something attempted
    to cross the authority boundary into broker execution.
    """


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> Any:
    # Keep logs robust; never throw while trying to log.
    try:
        json.dumps(value)
        return value
    except Exception:
        try:
            return str(value)
        except Exception:
            return "<unserializable>"


def fatal_if_execution_reached(
    *,
    operation: str,
    explicit_message: str,
    context: Mapping[str, Any] | None = None,
) -> NoReturn:
    """
    Absolute safety boundary: if reached, we must fail closed.

    - Logs an explicit CRITICAL event with context
    - Raises a fatal exception before any broker/network side effects
    """
    payload = {
        "ts": _utc_now_iso(),
        "intent_type": "fatal_execution_path_reached",
        "operation": str(operation),
        "message": str(explicit_message),
        "context": _safe_json(dict(context or {})),
        "repo_policy": "runtime_execution_forbidden",
    }
    # Emit both structured JSON and a plain string for greppability.
    logger.critical("FATAL: execution path reached; refusing. %s", json.dumps(payload, separators=(",", ":")))
    raise FatalExecutionPathError(explicit_message)

