"""
cloudrun_consumer entrypoint diagnostics

Runtime assumptions (documented for deploy/debug):
- Containers should follow the canonical repo layout:
  - COPY . /app
  - PYTHONPATH=/app
  - use absolute imports (e.g. `from cloudrun_consumer...`)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import logging

from fastapi import FastAPI, HTTPException, Request, Response

from cloudrun_consumer.event_utils import infer_topic
from cloudrun_consumer.firestore_writer import FirestoreWriter
from cloudrun_consumer.replay_support import ReplayContext, write_replay_marker
from cloudrun_consumer.schema_router import route_payload
from cloudrun_consumer.time_audit import ensure_utc

def _startup_diag(event_type: str, *, severity: str = "INFO", **fields: Any) -> None:
    """Print a structured JSON diagnostic log."""
    payload: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": str(severity).upper(),
        "service": "cloudrun-pubsub-firestore-materializer",
        "event_type": str(event_type),
    }
    payload.update(fields)
    try:
        sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except Exception:
        return
SERVICE_NAME = "cloudrun-pubsub-firestore-materializer"
DLQ_SAMPLE_RATE_DEFAULT = "0.01"
DLQ_SAMPLE_TTL_HOURS_DEFAULT = "72"

_logger = logging.getLogger("cloudrun_consumer")
if not _logger.handlers:
    _h = logging.StreamHandler(stream=sys.stdout)
    _h.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_h)
_logger.setLevel(str(os.getenv("LOG_LEVEL") or "INFO").upper())
_logger.propagate = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_rfc3339(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, source="cloudrun_consumer.main._parse_rfc3339", field="datetime")
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return ensure_utc(datetime.fromisoformat(s), source="cloudrun_consumer.main._parse_rfc3339", field="iso_string")
    except Exception:
        return None


def log(event_type: str, *, severity: str = "INFO", **fields: Any) -> None:
    payload: dict[str, Any] = {
        "timestamp": _utc_now().isoformat(),
        "severity": str(severity).upper(),
        "service": SERVICE_NAME,
        "env": os.getenv("ENV") or "unknown",
        "event_type": str(event_type),
    }
    payload.update(fields)
    try:
        msg = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        sev = str(severity).upper()
        if sev in {"ERROR", "CRITICAL", "ALERT", "EMERGENCY"}:
            _logger.error(msg)
        elif sev in {"WARNING"}:
            _logger.warning(msg)
        elif sev in {"DEBUG"}:
            _logger.debug(msg)
        else:
            _logger.info(msg)
    except Exception:
        return


def _require_json_content_type(req: Request) -> None:
    ct = str(req.headers.get("content-type") or "").strip()
    if ("\n" in ct) or ("\r" in ct):
        raise HTTPException(status_code=400, detail="invalid_header_value")
    if "application/json" not in ct.lower():
        raise HTTPException(status_code=415, detail="unsupported_media_type")


def _coerce_system_event_to_envelope(
    *, payload: dict[str, Any], message_id: str, published_at: datetime
) -> dict[str, Any]:
    """
    Legacy adapter: payload-only system event record -> EventEnvelopeV1.
    """
    ts = payload.get("timestamp")
    ts_s = str(ts).strip() if isinstance(ts, str) else ""
    if not ts_s:
        ts_s = published_at.isoformat()
    agent = str(payload.get("service") or "unknown").strip() or "unknown"
    sha = str(payload.get("git_sha") or payload.get("sha") or "unknown").strip() or "unknown"
    trace = str(payload.get("correlation_id") or payload.get("request_id") or message_id).strip() or message_id
    ev_type = str(payload.get("event_type") or payload.get("event") or "system.event").strip() or "system.event"
    return {
        "schemaVersion": 1,
        "event_type": ev_type,
        "agent_name": agent,
        "git_sha": sha,
        "ts": ts_s,
        "trace_id": trace,
        "payload": payload,
    }


def _is_event_envelope_v1(obj: dict[str, Any]) -> bool:
    return (
        isinstance(obj.get("schemaVersion"), int)
        and obj.get("schemaVersion") == 1
        and isinstance(obj.get("event_type"), str)
        and isinstance(obj.get("agent_name"), str)
        and isinstance(obj.get("git_sha"), str)
        and isinstance(obj.get("ts"), str)
        and isinstance(obj.get("trace_id"), str)
        and isinstance(obj.get("payload"), dict)
    )


app = FastAPI(title="Cloud Run Pub/Sub → Firestore Materializer", version="0.2.0")


@app.on_event("startup")
async def _startup() -> None:
    _normalize_env_alias("GCP_PROJECT", ["GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GCP_PROJECT_ID", "PROJECT_ID"])
    # Centralized env contract validation (single-line failure).
    try:
        from backend.common.config import validate_or_exit as _validate_or_exit  # noqa: WPS433

        _validate_or_exit("cloudrun-consumer")
    except SystemExit:
        raise
    except Exception as e:
        raise RuntimeError(f"CONFIG_FAIL service=cloudrun-consumer action=\"config_validation_import_failed:{type(e).__name__}:{e}\"") from e

    project_id = _require_env("GCP_PROJECT")

    database = os.getenv("FIRESTORE_DATABASE") or "(default)"
    collection_prefix = os.getenv("FIRESTORE_COLLECTION_PREFIX") or ""
    app.state.firestore_writer = FirestoreWriter(project_id=project_id, database=database, collection_prefix=collection_prefix)
    app.state.loop_heartbeat_monotonic = time.monotonic()


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": SERVICE_NAME, "ts": _utc_now().isoformat()}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    ok = bool(getattr(app.state, "firestore_writer", None))
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "not_ready", "service": SERVICE_NAME}


@app.get("/livez")
async def livez(response: Response) -> dict[str, Any]:
    now = time.monotonic()
    last = float(getattr(app.state, "loop_heartbeat_monotonic", 0.0) or 0.0)
    max_age_s = float(os.getenv("LIVEZ_MAX_AGE_S") or "60")
    age_s = max(0.0, now - last)
    ok = age_s <= max_age_s
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "wedged", "age_seconds": age_s, "max_age_seconds": max_age_s}


@app.post("/pubsub/push")
async def pubsub_push(req: Request) -> dict[str, Any]:
    app.state.loop_heartbeat_monotonic = time.monotonic()
    _require_json_content_type(req)

    try:
        body = await req.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid_json") from e
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_envelope")

    subscription = body.get("subscription")
    subscription_str = str(subscription).strip() if subscription is not None else ""
    if not subscription_str:
        log(
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_envelope",
            error="missing_subscription",
            messageId=None,
            publishTime=None,
            subscription="",
        )
        raise HTTPException(status_code=400, detail="missing_subscription")

    try:
        hdr = _validate_pubsub_headers(req=req, subscription_from_body=subscription_str)
    except HTTPException as e:
        log(
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_headers",
            error=str(getattr(e, "detail", "")),
            messageId=None,
            publishTime=None,
            subscription=subscription_str,
        )
        raise

    message = body.get("message")
    if not isinstance(message, dict):
        log(
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_envelope",
            error="missing_message",
            messageId=None,
            publishTime=None,
            subscription=subscription_str,
        )
        raise HTTPException(status_code=400, detail="invalid_envelope")

    message_id = str(msg.get("messageId") or "").strip()
    if not message_id:
        raise HTTPException(status_code=400, detail="missing_messageId")

    delivery_attempt_raw = message.get("deliveryAttempt")
    delivery_attempt: Optional[int] = None
    if isinstance(delivery_attempt_raw, int):
        delivery_attempt = delivery_attempt_raw
    else:
        try:
            if delivery_attempt_raw is not None and str(delivery_attempt_raw).strip():
                delivery_attempt = int(str(delivery_attempt_raw).strip())
        except Exception:
            delivery_attempt = None

    publish_time_raw = str(message.get("publishTime") or "").strip() or None
    publish_time = _parse_rfc3339(message.get("publishTime")) or _utc_now()
    attributes_raw = message.get("attributes") or {}
    attributes: dict[str, str] = {}
    if isinstance(attributes_raw, dict):
        for k, v in attributes_raw.items():
            if k is None:
                continue
            attributes[str(k)] = "" if v is None else str(v)

    writer: FirestoreWriter = app.state.firestore_writer
    dlq_sample_rate = float(os.getenv("DLQ_SAMPLE_RATE") or DLQ_SAMPLE_RATE_DEFAULT)
    dlq_sample_ttl_hours = float(os.getenv("DLQ_SAMPLE_TTL_HOURS") or DLQ_SAMPLE_TTL_HOURS_DEFAULT)

    def _ack_invalid(*, reason: str, error: str, handler: str, payload: dict[str, Any], errors: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        log(
            "contract.invalid",
            severity="ERROR",
            reason=reason,
            error=error,
            errors=errors[:10] if isinstance(errors, list) else None,
            topic=topic,
            subscription=subscription,
            messageId=message_id,
        )
        writer.maybe_write_sampled_dlq_event(
            message_id=message_id,
            subscription=subscription,
            topic=topic,
            handler=handler,
            http_status=200,
            reason=reason,
            error=error,
            delivery_attempt=None,
            attributes=attributes,
            payload=payload,
            sample_rate=dlq_sample_rate,
            ttl_hours=dlq_sample_ttl_hours,
        )
        try_write_contract_violation_alert(
            topic=str(topic),
            producer=str(payload.get("agent_name") or payload.get("service") or ""),
            event_type=str(payload.get("event_type") or ""),
            message=str(reason),
            errors=(errors or []),
            sample={"payload": payload},
        )
        return {"ok": True, "applied": False, "reason": reason}

    # Coerce/validate canonical envelope per topic.
    envelope: dict[str, Any]
    if _is_event_envelope_v1(decoded):
        envelope = decoded
    elif topic == "system-events":
        envelope = _coerce_system_event_to_envelope(payload=decoded, message_id=message_id, published_at=publish_time)
    else:
        return _ack_invalid(reason="missing_event_envelope", error="expected_EventEnvelopeV1", handler="none", payload=decoded)

    schema_errors = None
    try:
        schema_errors = validate_topic_event(topic=topic, event=envelope)
    except Exception as e:
        return _ack_invalid(
            reason="schema_validation_error",
            error=f"{type(e).__name__}:{e}",
            handler="none",
            payload=envelope,
        )
    if schema_errors:
        return _ack_invalid(
            reason="schema_validation_failed",
            error="invalid_event_for_topic",
            handler="none",
            payload=envelope,
            errors=schema_errors,
        )

    inner_payload = envelope.get("payload")
    assert isinstance(inner_payload, dict)

    handler = route_payload(payload=inner_payload, attributes=attributes, topic=topic)
    if handler is None:
        return _ack_invalid(reason="unroutable_payload", error="no_handler", handler="none", payload=envelope)

    # Business processing.
    try:
        res = handler.handler(
            payload=inner_payload,
            env=os.getenv("ENV") or "unknown",
            default_region=os.getenv("DEFAULT_REGION") or "unknown",
            source_topic=str(topic),
            message_id=message_id,
            pubsub_published_at=publish_time,
            firestore_writer=writer,
            replay=None,
        )
        log(
            "materialize.ok",
            severity="INFO",
            handler=handler.name,
            topic=topic,
            subscription=subscription,
            messageId=message_id,
            applied=res.get("applied"),
            reason=res.get("reason"),
        )
        return {"ok": True, **res}
    except ValueError as e:
        # Poison: ACK and record.
        return _ack_invalid(reason="handler_value_error", error=str(e), handler=handler.name, payload=envelope)
    except Exception as e:
        log(
            "materialize.exception",
            severity="ERROR",
            handler=handler.name,
            topic=topic,
            subscription=subscription,
            messageId=message_id,
            error=str(e),
            exception=traceback.format_exc()[-8000:],
        )
        raise HTTPException(status_code=500, detail="materialize_exception") from e


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.getenv("PORT") or "8080")
    uvicorn.run("cloudrun_consumer.main:app", host="0.0.0.0", port=port, log_level="warning", access_log=False)

