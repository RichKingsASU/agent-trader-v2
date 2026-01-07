"""
Tiny structured logging helper (JSON lines to stdout).

Goal: make it easy to define log-based metrics in Cloud Logging without
introducing a logging framework dependency.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_json(*, intent_type: str, severity: str = "INFO", **fields: Any) -> None:
    """
    Emit a single-line JSON log to stdout.

    Conventions:
    - log_ts: when this log line was emitted
    - intent_type: stable field used for log-based metrics
    - severity: recognized by Google Cloud Logging
    """
    log_ts = _utc_now_iso()
    payload = {
        "intent_type": str(intent_type),
        "severity": str(severity),
        "log_ts": log_ts,
        **fields,
    }
    payload.setdefault("ts", log_ts)
    print(json.dumps(payload, separators=(",", ":"), ensure_ascii=False), flush=True)

