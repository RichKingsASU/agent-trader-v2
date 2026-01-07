from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.observability.agent_identity import get_agent_identity, require_identity_env
from backend.observability.correlation import get_or_create_correlation_id
from backend.observability.redaction import redact_dict


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


def _write_json(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
    try:
        sys.stdout.flush()
    except Exception:
        pass


def _base_fields(*, level: str) -> dict[str, Any]:
    ident = get_agent_identity()
    # Normalize to required keys where possible.
    base: dict[str, Any] = {
        "timestamp": _utc_ts(),
        "level": level,
        "repo_id": ident.get("repo_id"),
        "agent_name": ident.get("agent_name"),
        "agent_role": ident.get("agent_role"),
        "agent_mode": ident.get("agent_mode"),
        "git_sha": ident.get("git_sha"),
    }
    cid = get_or_create_correlation_id()
    base["correlation_id"] = cid
    # No separate trace context in this repo yet; keep replay-friendly by mirroring.
    base["trace_id"] = cid
    return base


def log_event(event_name: str, *, level: str = "INFO", **fields: Any) -> None:
    payload: dict[str, Any] = _base_fields(level=level.upper())
    payload["event_name"] = _clean_text(event_name, max_len=128)
    if fields:
        payload.update(fields)
    _write_json(payload)


def intent_start(intent_type: str, summary: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    Emit an intent log with outcome='started' and return an intent context for timing/end.
    """
    require_identity_env()  # fail-fast if identity is missing

    intent_id = str(uuid.uuid4())
    start = time.perf_counter()
    cid = get_or_create_correlation_id()
    safe_payload = redact_dict(payload or {})

    intent_type_c = _clean_text(intent_type, max_len=128)
    summary_c = _clean_text(summary, max_len=512)

    log: dict[str, Any] = _base_fields(level="INFO")
    log.update(
        {
            "intent_id": intent_id,
            "intent_type": intent_type_c,
            "intent_summary": summary_c,
            "intent_payload": safe_payload,
            "outcome": "started",
        }
    )
    _write_json(log)

    return {
        "intent_id": intent_id,
        "intent_type": intent_type_c,
        "intent_summary": summary_c,
        "intent_payload": safe_payload,
        "start_perf": start,
        "correlation_id": cid,
    }


def intent_end(intent_ctx: dict[str, Any], outcome: str, *, error: Any = None) -> None:
    """
    Emit an intent log with outcome in {success|failure|started} and duration_ms if available.
    """
    end = time.perf_counter()
    start = float(intent_ctx.get("start_perf") or end)
    duration_ms = max(0, int((end - start) * 1000))

    out = _clean_text(outcome, max_len=16).lower()
    if out not in {"success", "failure", "started"}:
        out = "success"

    log: dict[str, Any] = _base_fields(level=("ERROR" if out == "failure" else "INFO"))
    log["intent_id"] = intent_ctx.get("intent_id") or str(uuid.uuid4())
    log["intent_type"] = intent_ctx.get("intent_type") or "unknown"
    log["intent_summary"] = intent_ctx.get("intent_summary") or "unknown"
    log["intent_payload"] = redact_dict(intent_ctx.get("intent_payload") or {})
    log["outcome"] = out
    log["duration_ms"] = duration_ms

    if out == "failure" and error is not None:
        msg = _clean_text(getattr(error, "message", None) or getattr(error, "detail", None) or error, max_len=2000)
        log["error"] = {"message": msg}

    _write_json(log)


def log_agent_start_banner(*, summary: str, extra: Optional[dict[str, Any]] = None) -> None:
    """
    Standard startup identity banner intent.
    """
    ctx = intent_start("agent_start", summary, payload=extra or {})
    intent_end(ctx, "success")

