"""
Audit-mode logging enrichment (engineering evidence, not legal compliance).

Purpose:
- Provide consistent log context for "who/what/when/under what config" evidence.
- Keep behavior unchanged beyond logging enrichment.

Controls:
- AUDIT_MODE=true|false (default: true)
- Adds (when enabled): repo_id, agent_identity, build_fingerprint, correlation_id, intent_id
"""

from __future__ import annotations

import logging
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

# Context propagated within a process (best-effort; for async frameworks use middleware).
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")
_intent_id: ContextVar[str] = ContextVar("intent_id", default="-")


def _truthy_env(name: str, *, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    s = str(v).strip().lower()
    return s in {"1", "true", "t", "yes", "y", "on"}


def audit_mode_enabled() -> bool:
    # Default true (explicitly requested).
    return _truthy_env("AUDIT_MODE", default=True)


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set((value or "").strip() or "-")


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_intent_id(value: str | None) -> None:
    _intent_id.set((value or "").strip() or "-")


def get_intent_id() -> str:
    return _intent_id.get()


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _repo_id() -> str:
    # Prefer explicit runtime var, but keep a safe default for evidence.
    v = (os.getenv("REPO_ID") or "").strip()
    return v or "RichKingsASU/agent-trader-v2"


def _agent_identity(agent_name: Optional[str] = None) -> str:
    v = (agent_name or os.getenv("AGENT_NAME") or "").strip()
    return v or "unknown"


def _build_fingerprint() -> str:
    """
    Best-effort build fingerprint.

    Prefer explicit BUILD_FINGERPRINT, else combine common CI/build identifiers.
    """
    explicit = (os.getenv("BUILD_FINGERPRINT") or "").strip()
    if explicit:
        return explicit

    parts: list[str] = []
    for k in ("GIT_SHA", "COMMIT_SHA", "SHORT_SHA", "BUILD_SHA", "SOURCE_VERSION"):
        v = (os.getenv(k) or "").strip()
        if v:
            parts.append(v[:64])
            break

    # Cloud Run revision (immutable per deploy)
    rev = (os.getenv("K_REVISION") or "").strip()
    if rev:
        parts.append(f"rev:{rev[:128]}")

    # Optional container image digest if provided by the platform.
    img = (os.getenv("IMAGE_DIGEST") or os.getenv("CONTAINER_IMAGE") or "").strip()
    if img:
        parts.append(f"img:{img[:256]}")

    return "|".join(parts) if parts else "unknown"


AUDIT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s "
    "repo_id=%(repo_id)s agent=%(agent_identity)s build=%(build_fingerprint)s "
    "correlation_id=%(correlation_id)s intent_id=%(intent_id)s "
    "%(message)s"
)


class _AuditEnrichmentFilter(logging.Filter):
    def __init__(self, *, agent_name: Optional[str] = None) -> None:
        super().__init__(name="")
        self._agent_name = agent_name

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 (filter is required name)
        enabled = audit_mode_enabled()

        # Always attach fields to avoid formatter KeyError, even when AUDIT_MODE=false.
        record.repo_id = _repo_id() if enabled else "-"
        record.agent_identity = _agent_identity(self._agent_name) if enabled else _agent_identity(self._agent_name)
        record.build_fingerprint = _build_fingerprint() if enabled else "-"

        record.correlation_id = get_correlation_id()
        record.intent_id = get_intent_id()
        record.audit_mode = bool(enabled)
        record.audit_ts_utc = _utc_ts()
        return True


_ENRICHMENT_INSTALLED = False


def configure_audit_log_enrichment(*, agent_name: Optional[str] = None) -> None:
    """
    Idempotently install a root-logger filter that enriches LogRecords.

    Note: This does not change handlers/formatters. Use configure_basic_logging()
    in entrypoints to ensure the enriched fields are emitted.
    """
    global _ENRICHMENT_INSTALLED
    if _ENRICHMENT_INSTALLED:
        return
    root = logging.getLogger()
    root.addFilter(_AuditEnrichmentFilter(agent_name=agent_name))
    _ENRICHMENT_INSTALLED = True


def configure_basic_logging(*, level: str | int | None = None) -> None:
    """
    Entry-point friendly logging config using the audit-friendly formatter.

    Does not force reconfiguration if handlers already exist.
    """
    configure_audit_log_enrichment()
    lvl = level or os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=lvl, format=AUDIT_LOG_FORMAT)


def install_fastapi_audit_middleware(app: object) -> None:
    """
    Best-effort FastAPI middleware:
    - correlation_id from request headers (X-Correlation-Id / X-Request-Id)
    - intent_id from request headers (X-Intent-Id) when provided

    This only influences logging context and does not modify responses.
    """
    try:
        from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore
        from starlette.requests import Request  # type: ignore
        from starlette.types import ASGIApp  # type: ignore
    except Exception:
        return

    class _AuditContextMiddleware(BaseHTTPMiddleware):
        def __init__(self, asgi_app: "ASGIApp") -> None:
            super().__init__(asgi_app)

        async def dispatch(self, request: "Request", call_next):  # type: ignore[override]
            corr = (
                request.headers.get("x-correlation-id")
                or request.headers.get("x-request-id")
                or str(uuid.uuid4())
            )
            intent = request.headers.get("x-intent-id")
            set_correlation_id(corr)
            if intent:
                set_intent_id(intent)
            return await call_next(request)

    try:
        getattr(app, "add_middleware")(_AuditContextMiddleware)  # type: ignore[misc]
    except Exception:
        return

