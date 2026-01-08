"""
Tiny structured logging helper (JSON lines to stdout).

Goal: make it easy to define log-based metrics in Cloud Logging without
introducing a logging framework dependency.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env_any(*names: str, default: str = "unknown") -> str:
    for n in names:
        v = os.getenv(n)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return default


def log_json(*, intent_type: str, severity: str = "INFO", **fields: Any) -> None:
    """
    Emit a single-line JSON log to stdout.

    Conventions:
    - log_ts: when this log line was emitted
    - intent_type: stable field used for log-based metrics
    - severity: recognized by Google Cloud Logging
    """
    log_ts = _utc_now_iso()
    payload: dict[str, Any] = {
        "intent_type": str(intent_type),
        "severity": str(severity).upper(),
        "log_ts": log_ts,
        # Required baseline identity fields
        "service": _env_any("SERVICE_NAME", "SERVICE", "OTEL_SERVICE_NAME", "K_SERVICE", "AGENT_NAME", default="unknown"),
        "env": _env_any("ENVIRONMENT", "ENV", "APP_ENV", "DEPLOY_ENV", default="unknown"),
        # Canonical event name (preferred by most services)
        "event_type": str(intent_type),
        **fields,
    }
    payload.setdefault("ts", log_ts)
    try:
        sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        try:
            sys.stdout.flush()
        except Exception:
            pass
    except Exception:
        return

