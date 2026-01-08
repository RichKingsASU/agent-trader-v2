from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .models import AgentIntent


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(dt: Optional[datetime] = None) -> str:
    return (dt or _utc_now()).isoformat()


def _json_line(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


_SECRET_KEYS = {
    "api_key",
    "apikey",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "client_secret",
    "password",
    "passwd",
    "private_key",
    "authorization",
}


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            ks = str(k).strip().lower()
            if ks in _SECRET_KEYS or "secret" in ks or "token" in ks or "password" in ks:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(v) for v in obj)
    return obj


def _intent_log(intent_type: str, **fields: Any) -> None:
    service = str(os.getenv("SERVICE_NAME") or os.getenv("K_SERVICE") or os.getenv("AGENT_NAME") or "unknown").strip() or "unknown"
    env = str(os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("APP_ENV") or os.getenv("DEPLOY_ENV") or "unknown").strip() or "unknown"
    payload = {
        "event_type": "intent",
        "intent_type": intent_type,
        "severity": str(fields.pop("severity", "INFO")).upper(),
        "log_ts": _ts(),
        "service": service,
        "env": env,
        **fields,
    }
    payload.setdefault("ts", payload["log_ts"])
    try:
        sys.stdout.write(_json_line(payload) + "\n")
        try:
            sys.stdout.flush()
        except Exception:
            pass
    except Exception:
        return


def _audit_root() -> Path:
    return Path(os.getenv("AUDIT_ARTIFACTS_DIR") or "audit_artifacts")


def _intent_audit_path(now: Optional[datetime] = None) -> Path:
    d = (now or _utc_now()).date().isoformat()
    return _audit_root() / "agent_intents" / d / "intents.ndjson"


def emit_agent_intent(intent: AgentIntent) -> None:
    """
    Emit an agent intent:
    - logs a summary to stdout
    - writes the full payload (redacted) to append-only NDJSON under audit_artifacts/

    Safety: this function never sizes or executes.
    """
    _intent_log(
        "agent_intent",
        event="emitted",
        intent_id=str(intent.intent_id),
        strategy_name=intent.strategy_name,
        symbol=intent.symbol,
        side=intent.side.value,
        kind=intent.kind.value,
        confidence=intent.confidence,
        valid_until_utc=intent.constraints.valid_until_utc.isoformat(),
        requires_human_approval=bool(intent.constraints.requires_human_approval),
    )

    try:
        audit_path = _intent_audit_path(intent.created_at_utc)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        raw = intent.model_dump(mode="json")  # type: ignore[attr-defined]

        # Redact nested indicators before persistence.
        raw_rationale = raw.get("rationale") or {}
        if isinstance(raw_rationale, dict):
            raw_rationale["indicators"] = _redact(raw_rationale.get("indicators") or {})
            raw["rationale"] = raw_rationale

        with audit_path.open("a", encoding="utf-8") as f:
            f.write(_json_line(raw) + "\n")
    except Exception as e:
        _intent_log(
            "agent_intent",
            event="audit_write_failed",
            intent_id=str(intent.intent_id),
            error=str(e),
            severity="WARNING",
        )

