from __future__ import annotations

import logging
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Mapping, Optional


_CORRELATION_ID: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
logger = logging.getLogger(__name__)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _clean_id(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    # Bound length and allow only safe characters to avoid log injection.
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) > 128:
        s = s[:128]
    if _SAFE_ID_RE.match(s):
        return s
    return None


def _header_get(headers: Mapping[str, Any], name: str) -> Optional[str]:
    # tolerate case differences
    for k, v in headers.items():
        if str(k).lower() == name.lower():
            return str(v)
    return None


def generate_correlation_id() -> str:
    return str(uuid.uuid4())


def get_correlation_id() -> Optional[str]:
    return _CORRELATION_ID.get()


def get_or_create_correlation_id(
    *,
    headers: Optional[Mapping[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> str:
    """
    Get correlation id from:
    - explicit correlation_id
    - headers: X-Request-Id (preferred), X-Correlation-Id (fallback)
    - existing contextvar
    - else generate a new uuid4
    """
    cleaned = _clean_id(correlation_id)
    if cleaned:
        _CORRELATION_ID.set(cleaned)
        return cleaned

    if headers:
        raw = _header_get(headers, "X-Request-Id") or _header_get(headers, "X-Correlation-Id")
        cleaned = _clean_id(raw)
        if cleaned:
            _CORRELATION_ID.set(cleaned)
            return cleaned

    existing = _clean_id(get_correlation_id())
    if existing:
        return existing

    cid = generate_correlation_id()
    _CORRELATION_ID.set(cid)
    return cid


@contextmanager
def bind_correlation_id(
    *,
    headers: Optional[Mapping[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> str:
    cid = get_or_create_correlation_id(headers=headers, correlation_id=correlation_id)
    token = _CORRELATION_ID.set(cid)
    try:
        yield cid
    finally:
        _CORRELATION_ID.reset(token)


def install_fastapi_correlation_middleware(app: Any) -> None:
    """
    Install correlation ID middleware on a FastAPI app (best-effort).

    - Reads X-Request-Id (preferred) / X-Correlation-Id (fallback)
    - Binds correlation_id in a contextvar for the request lifetime
    - Echoes X-Request-Id (+ X-Correlation-Id back-compat) on the response for easier tracing
    """
    try:
        # Avoid importing fastapi types at module import time.
        from starlette.requests import Request  # noqa: WPS433
    except Exception:
        logger.exception("observability.correlation.middleware_import_failed")
        return

    @app.middleware("http")
    async def _correlation_mw(request: "Request", call_next):  # type: ignore[name-defined]
        headers = dict(request.headers)
        with bind_correlation_id(headers=headers) as cid:
            resp = await call_next(request)
            try:
                resp.headers["X-Request-Id"] = cid
                resp.headers["X-Correlation-Id"] = cid
            except Exception:
                logger.exception("observability.correlation.response_header_set_failed")
                pass
            return resp

