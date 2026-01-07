"""
Structured replay events for post-mortem decision reconstruction.

This module emits a single-line JSON object per replay-relevant event so that
offline tooling can reconstruct timelines across services.

Design goals:
- Human-safe: best-effort redaction of secrets/tokens.
- Log-friendly: one JSON object per line, safe to embed in regular logging.
- Stable schema: includes `replay_schema` and `event` for parsing.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional


REPLAY_SCHEMA = "agenttrader.replay.v1"

# Common secret-ish keys that must never appear in replay logs.
_SECRET_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "password",
    "authorization",
    "cookie",
    "bearer",
    "private_key",
    "key_id",
    "client_secret",
)

_MAX_STRING_LEN = 2000
_MAX_CONTAINER_LEN = 200


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _is_secret_key(key: str) -> bool:
    k = str(key).strip().lower()
    return any(frag in k for frag in _SECRET_KEY_FRAGMENTS)


def _truncate_str(s: str) -> str:
    if len(s) <= _MAX_STRING_LEN:
        return s
    return s[: _MAX_STRING_LEN - 20] + "...<truncated>"


def _sanitize(value: Any, *, _depth: int = 0) -> Any:
    """
    Best-effort "no secrets" conversion + size limiting.
    """
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()

    # Depth guard to avoid massive payloads.
    if _depth >= 6:
        return "<max_depth>"

    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_CONTAINER_LEN:
                out["<truncated_keys>"] = True
                break
            ks = str(k)
            if _is_secret_key(ks):
                out[ks] = "<redacted>"
            else:
                out[ks] = _sanitize(v, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        out_list = []
        for i, v in enumerate(value):
            if i >= _MAX_CONTAINER_LEN:
                out_list.append("<truncated_list>")
                break
            out_list.append(_sanitize(v, _depth=_depth + 1))
        return out_list

    # Fallback: stringify
    return _truncate_str(str(value))


# Context propagation (optional).
_ctx_trace_id: ContextVar[Optional[str]] = ContextVar("replay_trace_id", default=None)
_ctx_agent_name: ContextVar[Optional[str]] = ContextVar("replay_agent_name", default=None)

_PROCESS_TRACE_ID = (os.getenv("TRACE_ID") or "").strip() or uuid.uuid4().hex


def set_replay_context(*, trace_id: Optional[str] = None, agent_name: Optional[str] = None) -> None:
    if trace_id is not None:
        _ctx_trace_id.set(trace_id)
    if agent_name is not None:
        _ctx_agent_name.set(agent_name)


def get_replay_context() -> dict[str, Optional[str]]:
    return {"trace_id": _ctx_trace_id.get(), "agent_name": _ctx_agent_name.get()}


def _default_agent_name(*, fallback: str = "agenttrader") -> str:
    return (
        (_ctx_agent_name.get() or "").strip()
        or (os.getenv("AGENT_NAME") or "").strip()
        or fallback
    )


def _default_trace_id() -> str:
    return (_ctx_trace_id.get() or "").strip() or _PROCESS_TRACE_ID


def build_replay_event(
    *,
    event: str,
    data: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    component: Optional[str] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns a JSON-serializable replay event dict. Caller chooses how to log/emit it.
    """
    obj: Dict[str, Any] = {
        "replay_schema": REPLAY_SCHEMA,
        "ts": _utc_now_iso(),
        "event": str(event),
        "trace_id": (trace_id or "").strip() or _default_trace_id(),
        "agent_name": (agent_name or "").strip() or _default_agent_name(),
    }
    if component:
        obj["component"] = str(component)
    if run_id:
        obj["run_id"] = str(run_id)
    if data:
        obj["data"] = _sanitize(data)

    # Helpful but non-essential metadata
    obj["meta"] = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "mono_ms": int(time.monotonic() * 1000),
    }
    return obj


def dumps_replay_event(obj: Dict[str, Any]) -> str:
    """
    Compact JSON string for embedding into normal logs.
    """
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

