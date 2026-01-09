"""
Execution ID context propagation for structured logs.

This mirrors the existing `backend.observability.correlation` primitive, but for
an execution-scoped identifier (e.g. trade execution attempt / order intent).

Design:
- Best-effort and stdlib-only
- Never *forces* generation unless the caller opts in via get_or_create
- Safe default: logs still include `execution_id` (as null) when unknown
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional


_EXECUTION_ID: ContextVar[Optional[str]] = ContextVar("execution_id", default=None)


def _clean_id(value: str | None) -> str | None:
    if value is None:
        return None
    s = str(value).replace("\n", " ").replace("\r", " ").strip()
    if not s:
        return None
    # Keep bounded to avoid log bloat / header abuse.
    return s[:128]


def generate_execution_id() -> str:
    return uuid.uuid4().hex


def get_execution_id() -> str | None:
    return _clean_id(_EXECUTION_ID.get())


def set_execution_id(value: str | None) -> None:
    _EXECUTION_ID.set(_clean_id(value))


def get_or_create_execution_id(*, execution_id: str | None = None) -> str:
    cleaned = _clean_id(execution_id)
    if cleaned:
        _EXECUTION_ID.set(cleaned)
        return cleaned
    existing = get_execution_id()
    if existing:
        return existing
    eid = generate_execution_id()
    _EXECUTION_ID.set(eid)
    return eid


@contextmanager
def bind_execution_id(*, execution_id: str | None = None):
    """
    Bind execution_id into a contextvar for the scope lifetime.
    """
    token = _EXECUTION_ID.set(_clean_id(execution_id))
    try:
        yield get_execution_id()
    finally:
        _EXECUTION_ID.reset(token)

