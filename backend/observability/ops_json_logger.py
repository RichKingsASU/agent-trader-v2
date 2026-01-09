"""
Ops-friendly structured JSON logging (one JSON object per line).

Primary goal: make logs queryable in Google Cloud Logging by emitting
consistent fields, especially:
- service
- git_sha
- image_tag
- agent_mode
- severity

This module is intentionally stdlib-only.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, MutableMapping, Optional

from backend.observability.correlation import get_or_create_correlation_id
from backend.observability.execution_id import get_execution_id


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


def _normalize_severity(severity: str | None) -> str:
    s = _clean_text(severity or "INFO", max_len=16).upper()
    # Cloud Logging supports: DEFAULT, DEBUG, INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT, EMERGENCY
    allowed = {"DEFAULT", "DEBUG", "INFO", "NOTICE", "WARNING", "ERROR", "CRITICAL", "ALERT", "EMERGENCY"}
    if s in allowed:
        return s
    # common aliases
    if s in {"WARN"}:
        return "WARNING"
    if s in {"FATAL"}:
        return "CRITICAL"
    return "INFO"


def _default_service() -> str:
    # Prefer explicit overrides; fall back to Cloud Run; then agent name; then unknown.
    return _env_any("SERVICE_NAME", "SERVICE", "OTEL_SERVICE_NAME", "K_SERVICE", "AGENT_NAME", default="unknown", max_len=128)


def _default_env() -> str:
    return _env_any("ENVIRONMENT", "ENV", "APP_ENV", "DEPLOY_ENV", default="unknown", max_len=64)


def _default_sha() -> str:
    return _env_any(
        "GIT_SHA",
        "GITHUB_SHA",
        "COMMIT_SHA",
        "SHORT_SHA",
        "BUILD_SHA",
        "SOURCE_VERSION",
        default="unknown",
        max_len=64,
    )


def _default_version() -> str:
    return _env_any("AGENT_VERSION", "APP_VERSION", "VERSION", "IMAGE_TAG", "K_REVISION", default="unknown", max_len=128)


def _base_fields(*, service: str | None, severity: str) -> dict[str, Any]:
    cid = get_or_create_correlation_id()
    sha = _default_sha()
    return {
        "timestamp": _utc_ts(),
        "severity": _normalize_severity(severity),
        "service": _clean_text(service or _default_service(), max_len=128) or "unknown",
        # Required stable identity fields
        "env": _default_env(),
        "version": _default_version(),
        "sha": sha,
        "git_sha": sha,  # back-compat
        "image_tag": _env_any("IMAGE_TAG", "IMAGE_REF", "K_REVISION", default="unknown", max_len=256),
        "agent_mode": _env_any("AGENT_MODE", "MODE", "RUN_MODE", default="unknown", max_len=32),
        # Request/correlation
        "request_id": cid,
        "correlation_id": cid,
        "execution_id": get_execution_id(),
    }


def _write_json(obj: Mapping[str, Any]) -> None:
    try:
        sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
        try:
            sys.stdout.flush()
        except Exception:
            pass
    except Exception:
        # Never break service behavior due to logging.
        return


def log(service: str | None, event: str, *, severity: str = "INFO", **fields: Any) -> None:
    payload: dict[str, Any] = _base_fields(service=service, severity=severity)
    ev = _clean_text(event, max_len=128)
    payload["event_type"] = ev
    payload["event"] = ev  # back-compat
    if fields:
        payload.update(fields)
    _write_json(payload)


@dataclass(frozen=True)
class OpsLogger:
    """
    Convenience wrapper that pins `service` and provides common ops events.
    """

    service: str

    def event(self, event: str, *, severity: str = "INFO", **fields: Any) -> None:
        log(self.service, event, severity=severity, **fields)

    def startup_fingerprint(self, **fields: Any) -> None:
        self.event("startup_fingerprint", severity="INFO", **fields)

    def readiness(self, *, ready: bool = True, **fields: Any) -> None:
        self.event("readiness", severity="INFO", ready=bool(ready), **fields)

    def reconnect_attempt(self, *, attempt: int | None = None, sleep_s: float | None = None, **fields: Any) -> None:
        payload: dict[str, Any] = dict(fields)
        if attempt is not None:
            payload["attempt"] = int(attempt)
        if sleep_s is not None:
            payload["sleep_s"] = float(sleep_s)
        self.event("reconnect_attempt", severity="WARNING", **payload)

    def heartbeat(self, *, kind: str = "loop", **fields: Any) -> None:
        self.event("heartbeat", severity="INFO", kind=_clean_text(kind, max_len=64), **fields)

    def shutdown(self, *, phase: str = "initiated", **fields: Any) -> None:
        self.event("shutdown", severity="INFO", phase=_clean_text(phase, max_len=32), **fields)


_once_lock = threading.Lock()
_once_keys: set[str] = set()


def log_once(service: str | None, key: str, event: str, *, severity: str = "INFO", **fields: Any) -> None:
    """
    Idempotent log helper for process-level one-time events.
    """
    k = _clean_text(key, max_len=128)
    with _once_lock:
        if k in _once_keys:
            return
        _once_keys.add(k)
    log(service, event, severity=severity, **fields)

