"""
Universal agent identity + intent logging.

This module intentionally logs only a small, explicit allowlist of fields and
never echoes arbitrary environment variables (to avoid leaking secrets).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_text(s: Any, *, max_len: int) -> str:
    """
    Best-effort sanitization for log fields:
    - stringifies
    - strips newlines
    - trims and bounds length
    """
    try:
        v = str(s) if s is not None else ""
    except Exception:
        v = ""
    v = v.replace("\n", " ").replace("\r", " ").strip()
    if len(v) > max_len:
        v = v[: max_len - 1] + "…"
    return v


def _truthy_env(name: str) -> Optional[bool]:
    v = os.getenv(name)
    if v is None:
        return None
    s = v.strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    return None


def _get_git_sha() -> str:
    # Prefer explicit runtime var; fall back to common CI vars.
    for k in ("GIT_SHA", "COMMIT_SHA", "SHORT_SHA", "BUILD_SHA", "SOURCE_VERSION"):
        v = os.getenv(k)
        if v and v.strip():
            return _sanitize_text(v.strip(), max_len=64)
    return "unknown"


def _get_agent_mode() -> str:
    for k in ("AGENT_MODE", "MODE", "RUN_MODE"):
        v = os.getenv(k)
        if v and v.strip():
            return _sanitize_text(v.strip(), max_len=32)

    # Common dry-run toggles used in this repo.
    for k in ("EXEC_DRY_RUN", "DRY_RUN"):
        b = _truthy_env(k)
        if b is True:
            return "dry_run"
        if b is False:
            return "live"

    return "unknown"


def _get_environment() -> str:
    for k in ("ENVIRONMENT", "APP_ENV", "DEPLOY_ENV", "ENV"):
        v = os.getenv(k)
        if v and v.strip():
            return _sanitize_text(v.strip(), max_len=32)
    return "unknown"


def _get_service() -> Optional[str]:
    # Cloud Run
    for k in ("K_SERVICE",):
        v = os.getenv(k)
        if v and v.strip():
            return _sanitize_text(v.strip(), max_len=128)
    # Generic / OpenTelemetry
    for k in ("SERVICE", "OTEL_SERVICE_NAME"):
        v = os.getenv(k)
        if v and v.strip():
            return _sanitize_text(v.strip(), max_len=128)
    return None


def _get_workload() -> Optional[str]:
    # Prefer explicit vars if provided via manifest/CI.
    for k in ("WORKLOAD", "WORKLOAD_NAME", "K8S_WORKLOAD"):
        v = os.getenv(k)
        if v and v.strip():
            return _sanitize_text(v.strip(), max_len=128)

    # Kubernetes: HOSTNAME is typically the Pod name.
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        hn = os.getenv("HOSTNAME")
        if hn and hn.strip():
            return _sanitize_text(hn.strip(), max_len=128)
    return None


def configure_startup_logging(agent_name: str, intent: str) -> None:
    """
    Emit a single JSON line describing this agent's identity and intent.

    Required fields:
    - ts, agent_name, intent, git_sha, agent_mode, environment
    Optional fields (included when available):
    - service, workload

    Safety:
    - Only logs explicit allowlisted values (does not dump env)
    - Never raises
    """
    try:
        payload: dict[str, Any] = {
            "ts": _utc_ts(),
            "agent_name": _sanitize_text(agent_name, max_len=128) or "unknown",
            "intent": _sanitize_text(intent, max_len=512) or "unknown",
            "git_sha": _get_git_sha(),
            "agent_mode": _get_agent_mode(),
            "environment": _get_environment(),
        }

        service = _get_service()
        if service:
            payload["service"] = service

        workload = _get_workload()
        if workload:
            payload["workload"] = workload

        # Single-line JSON to stdout for container log collectors.
        print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)
    except Exception:
        # Never break startup for logging.
        return

