"""
Structured JSON logging + request/correlation IDs (stdlib-only).

Goals:
- One JSON object per log line (stdout)
- Consistent core fields across backend services:
  - service, env, version, sha
  - request_id, correlation_id
  - event_type, severity
- For HTTP services (FastAPI/Starlette), middleware that:
  - reads/propagates X-Request-ID
  - binds correlation_id for the request lifetime
  - emits a single http.request log line per request
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Mapping, Optional


_REQUEST_ID: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
logger = logging.getLogger(__name__)

_RESERVED_ATTRS: frozenset[str] = frozenset(
    {
        # logging.LogRecord built-ins
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        # our injected keys
        "service",
        "env",
        "version",
        "sha",
        "request_id",
        "correlation_id",
        "event_type",
        "severity",
        "message",
        "timestamp",
    }
)


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(v: Any, *, max_len: int = 2000) -> str:
    try:
        s = "" if v is None else str(v)
    except Exception:
        s = ""
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _env_any(*names: str, default: str = "unknown", max_len: int = 256) -> str:
    for name in names:
        v = os.getenv(name)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return _clean_text(s, max_len=max_len)
    return default


def _normalize_severity(level: str | int | None) -> str:
    if isinstance(level, int):
        name = logging.getLevelName(level)
        return _normalize_severity(str(name))
    s = _clean_text(level or "INFO", max_len=16).upper()
    allowed = {"DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"}
    if s in allowed:
        return s
    if s == "WARN":
        return "WARNING"
    if s == "FATAL":
        return "CRITICAL"
    return "INFO"


def default_service_name() -> str:
    return _env_any("SERVICE_NAME", "SERVICE", "OTEL_SERVICE_NAME", "K_SERVICE", "AGENT_NAME", default="unknown", max_len=128)


def default_env_name() -> str:
    return _env_any("ENVIRONMENT", "ENV", "APP_ENV", "DEPLOY_ENV", default="unknown", max_len=64)


def default_sha() -> str:
    return _env_any("GIT_SHA", "GITHUB_SHA", "COMMIT_SHA", "SHORT_SHA", "BUILD_SHA", "SOURCE_VERSION", default="unknown", max_len=64)


def default_version() -> str:
    # Prefer explicit version; fall back to container/revision identifiers.
    return _env_any("AGENT_VERSION", "APP_VERSION", "VERSION", "IMAGE_TAG", "K_REVISION", default="unknown", max_len=128)


def get_request_id() -> Optional[str]:
    rid = _REQUEST_ID.get()
    return _clean_text(rid, max_len=128) if rid else None


def set_request_id(value: str | None) -> None:
    v = _clean_text(value, max_len=128)
    _REQUEST_ID.set(v if v else None)


@contextmanager
def bind_request_id(*, request_id: str | None = None) -> str:
    rid = _clean_text(request_id or "", max_len=128) or uuid.uuid4().hex
    token = _REQUEST_ID.set(rid)
    try:
        # Keep legacy audit context in sync when present.
        try:
            from backend.common.audit_logging import set_correlation_id as _set_audit_correlation_id  # noqa: WPS433

            _set_audit_correlation_id(rid)
        except Exception:
            logger.exception("logging.bind_request_id.audit_logging_sync_failed")
            pass

        # Keep observability correlation context in sync when present.
        try:
            from backend.observability.correlation import bind_correlation_id as _bind_corr  # noqa: WPS433

            with _bind_corr(correlation_id=rid):
                yield rid
                return
        except Exception:
            logger.exception("logging.bind_request_id.observability_correlation_sync_failed")
            yield rid
            return
    finally:
        _REQUEST_ID.reset(token)


class JsonLogFormatter(logging.Formatter):
    def __init__(self, *, service: str | None, env: str | None, version: str | None, sha: str | None) -> None:
        super().__init__()
        self._service = _clean_text(service or default_service_name(), max_len=128) or "unknown"
        self._env = _clean_text(env or default_env_name(), max_len=64) or "unknown"
        self._version = _clean_text(version or default_version(), max_len=128) or "unknown"
        self._sha = _clean_text(sha or default_sha(), max_len=64) or "unknown"

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 (format required by logging)
        severity = _normalize_severity(getattr(record, "severity", None) or record.levelname)
        event_type = _clean_text(getattr(record, "event_type", None) or "", max_len=128) or "log"
        rid = _clean_text(getattr(record, "request_id", None) or get_request_id() or "", max_len=128) or None
        cid = _clean_text(getattr(record, "correlation_id", None) or "", max_len=128) or None
        if not cid:
            # Ensure a stable correlation_id is always present for queryability.
            try:
                from backend.observability.correlation import get_or_create_correlation_id as _get_or_create_correlation_id  # noqa: WPS433

                cid = _get_or_create_correlation_id()
            except Exception:
                cid = uuid.uuid4().hex
        if not rid:
            rid = cid

        payload: dict[str, Any] = {
            "timestamp": _utc_ts(),
            "severity": severity,
            "service": _clean_text(getattr(record, "service", None) or self._service, max_len=128) or "unknown",
            "env": _clean_text(getattr(record, "env", None) or self._env, max_len=64) or "unknown",
            "version": _clean_text(getattr(record, "version", None) or self._version, max_len=128) or "unknown",
            "sha": _clean_text(getattr(record, "sha", None) or self._sha, max_len=64) or "unknown",
            "request_id": rid,
            "correlation_id": cid,
            "event_type": event_type,
            "message": _clean_text(record.getMessage(), max_len=4000),
            "logger": _clean_text(record.name, max_len=256),
        }

        # Attach exception details when present.
        if record.exc_info:
            try:
                payload["exception"] = "".join(traceback.format_exception(*record.exc_info))[-8000:]
            except Exception:
                payload["exception"] = "exception_format_failed"
        elif record.stack_info:
            payload["stack"] = _clean_text(record.stack_info, max_len=8000)

        # Include any extra fields provided via logger.*(..., extra={...})
        try:
            for k, v in record.__dict__.items():
                if k in _RESERVED_ATTRS:
                    continue
                if k.startswith("_"):
                    continue
                payload[str(k)] = v
        except Exception:
            pass

        return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def _silence_uvicorn_handlers() -> None:
    # Ensure uvicorn loggers flow through root and use our handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True


def init_structured_logging(
    *,
    service: str | None = None,
    env: str | None = None,
    version: str | None = None,
    sha: str | None = None,
    level: str | int | None = None,
) -> None:
    """
    Configure stdlib logging to emit JSON lines to stdout.

    Safe to call multiple times (last call wins).
    """
    lvl = level or os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(lvl)

    # Replace handlers to ensure JSON output.
    root.handlers = []
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(lvl)
    handler.setFormatter(JsonLogFormatter(service=service, env=env, version=version, sha=sha))
    root.addHandler(handler)

    # Make warnings go through logging (and therefore JSON).
    logging.captureWarnings(True)
    _silence_uvicorn_handlers()


def log_event(
    logger: logging.Logger,
    event_type: str,
    *,
    severity: str = "INFO",
    message: str | None = None,
    **fields: Any,
) -> None:
    """
    Convenience wrapper for semantic events with stable `event_type`.
    """
    lvl = getattr(logging, str(severity).upper(), logging.INFO)
    logger.log(
        lvl,
        message or event_type,
        extra={"event_type": _clean_text(event_type, max_len=128), **fields},
    )


def log_standard_event(
    logger: logging.Logger,
    event_type: str,
    *,
    severity: str = "INFO",
    message: str | None = None,
    correlation_id: str | None = None,
    event_id: str | None = None,
    topic: str | None = None,
    outcome: str | None = None,
    latency_ms: int | float | None = None,
    **fields: Any,
) -> None:
    """
    Emit a structured log line using stable, queryable keys across services.

    Required stable keys (when applicable):
    - service, env, version (handled by formatter defaults)
    - correlation_id, event_id, topic, outcome, latency_ms
    """
    extra: dict[str, Any] = dict(fields)
    if correlation_id is not None:
        extra["correlation_id"] = _clean_text(correlation_id, max_len=128)
    if event_id is not None:
        extra["event_id"] = _clean_text(event_id, max_len=256)
    if topic is not None:
        extra["topic"] = _clean_text(topic, max_len=512)
    if outcome is not None:
        extra["outcome"] = _clean_text(outcome, max_len=64)
    if latency_ms is not None:
        try:
            extra["latency_ms"] = int(max(0.0, float(latency_ms)))
        except Exception:
            # Keep the key stable, but avoid breaking logs on bad types.
            extra["latency_ms"] = None

    log_event(logger, event_type, severity=severity, message=message, **extra)


def install_fastapi_request_id_middleware(app: Any, *, service: str | None = None) -> None:
    """
    Best-effort FastAPI middleware:
    - Read/propagate X-Request-ID (preferred) / X-Correlation-Id (fallback)
    - Bind request_id + correlation_id context for request lifetime
    - Emit one http.request JSON log line per request
    """
    try:
        from starlette.requests import Request  # noqa: WPS433
        from starlette.responses import Response  # noqa: WPS433
    except Exception:
        # Best-effort; some runtimes may not include Starlette (or import may fail).
        logger.exception("logging.fastapi_request_id_middleware_import_failed")
        return

    http_logger = logging.getLogger("http")
    svc = _clean_text(service or default_service_name(), max_len=128) or "unknown"

    @app.middleware("http")
    async def _request_id_mw(request: "Request", call_next):  # type: ignore[name-defined]
        incoming = request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or None
        rid = _clean_text(incoming, max_len=128) or uuid.uuid4().hex
        try:
            # Cloud Run perf markers (stdlib-only).
            from backend.common.cloudrun_perf import classify_request as _classify_request  # noqa: WPS433

            req_class = _classify_request()
        except Exception:
            req_class = None
        start = time.perf_counter()
        status_code: int | None = None
        with bind_request_id(request_id=rid) as bound:
            try:
                resp: "Response" = await call_next(request)  # type: ignore[name-defined]
                status_code = int(getattr(resp, "status_code", 200))
            except Exception:
                status_code = 500
                raise
            finally:
                dur_ms = int(max(0.0, (time.perf_counter() - start) * 1000.0))
                try:
                    log_event(
                        http_logger,
                        "http.request",
                        severity="INFO",
                        service=svc,
                        request_id=bound,
                        correlation_id=bound,
                        method=request.method,
                        path=str(getattr(request.url, "path", "")),
                        status_code=status_code,
                        latency_ms=dur_ms,
                        duration_ms=dur_ms,  # back-compat
                        cold_start=bool(getattr(req_class, "cold_start", False)) if req_class is not None else None,
                        request_ordinal=int(getattr(req_class, "request_ordinal", 0)) if req_class is not None else None,
                        instance_uptime_ms=int(getattr(req_class, "instance_uptime_ms", 0)) if req_class is not None else None,
                    )
                except Exception:
                    # Avoid recursion: if logging is broken, don't try to log about it.
                    pass

        # Ensure callers can propagate across hops.
        try:
            resp.headers["X-Request-ID"] = bound  # type: ignore[name-defined]
            # Back-compat for existing callers.
            resp.headers["X-Correlation-Id"] = bound  # type: ignore[name-defined]
        except Exception:
            # Avoid recursion: header mutation failures are non-fatal.
            pass
        return resp

