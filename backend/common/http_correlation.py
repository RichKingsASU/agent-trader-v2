from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar
from typing import Callable

from fastapi import FastAPI, Request, Response

_cid: ContextVar[str | None] = ContextVar("correlation_id", default=None)

logger = logging.getLogger("http")


def get_correlation_id() -> str | None:
    return _cid.get()


def install_http_correlation(app: FastAPI, *, service: str) -> None:
    """
    Add:
    - X-Correlation-Id response header
    - a single structured JSON log line per request containing correlation_id

    This is ops/observability only; it does not modify business logic.
    """

    @app.middleware("http")
    async def _correlation_middleware(request: Request, call_next: Callable) -> Response:
        cid = (
            request.headers.get("x-correlation-id")
            or request.headers.get("x-request-id")
            or uuid.uuid4().hex
        )
        token = _cid.set(cid)
        start = time.time()
        status_code: int | None = None
        try:
            response: Response = await call_next(request)
            status_code = int(getattr(response, "status_code", 200))
        except Exception:
            status_code = 500
            raise
        finally:
            dur_ms = int(max(0.0, (time.time() - start) * 1000.0))
            try:
                logger.info(
                    "http.request %s",
                    json.dumps(
                        {
                            "service": service,
                            "correlation_id": cid,
                            "method": request.method,
                            "path": request.url.path,
                            "status_code": status_code,
                            "duration_ms": dur_ms,
                        },
                        separators=(",", ":"),
                    ),
                )
            except Exception:
                # Preserve stack traces, but never break request handling.
                logger.exception("http.request_log_failed service=%s", service)
                pass
            _cid.reset(token)

        # ensure caller can propagate across hops
        response.headers["X-Correlation-Id"] = cid
        return response

