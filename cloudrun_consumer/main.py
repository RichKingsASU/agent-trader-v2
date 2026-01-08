from __future__ import annotations

import base64
import json
import traceback
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

from event_utils import infer_topic
from firestore_writer import FirestoreWriter
from schema_router import route_payload


SERVICE_NAME = "cloudrun-pubsub-firestore-materializer"
DLQ_SAMPLE_RATE_DEFAULT = "0.01"  # 1% (deterministic per messageId)
DLQ_SAMPLE_TTL_HOURS_DEFAULT = "72"

_logger = logging.getLogger("cloudrun_consumer")
if not _logger.handlers:
    _handler = logging.StreamHandler(stream=sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)
_logger.setLevel(str(os.getenv("LOG_LEVEL") or "INFO").upper())
_logger.propagate = False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_rfc3339(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        log("time.parse_failed", severity="ERROR", value=s, exception=traceback.format_exc()[-8000:])
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
        sev = str(severity).upper()
        if sev in {"ERROR", "CRITICAL", "ALERT", "EMERGENCY"}:
            _logger.error(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        elif sev in {"WARNING"}:
            _logger.warning(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        elif sev in {"DEBUG"}:
            _logger.debug(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
        else:
            _logger.info(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    except Exception:
        # Preserve stack traces even if stdout/serialization is broken.
        try:
            sys.stderr.write(
                json.dumps(
                    {
                        "timestamp": _utc_now().isoformat(),
                        "severity": "ERROR",
                        "service": SERVICE_NAME,
                        "event_type": "logging.emit_failed",
                        "exception": traceback.format_exc()[-8000:],
                    },
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stderr.flush()
        except Exception:
            return


def _require_env(name: str, *, default: Optional[str] = None) -> str:
    v = os.getenv(name)
    if v is None or not str(v).strip():
        if default is not None:
            return default
        raise RuntimeError(f"Missing required env var: {name}")
    return str(v).strip()

def _float_env(name: str, *, default: str) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        raw = default
    try:
        return float(raw)
    except Exception:
        try:
            return float(default)
        except Exception:
            return 0.0


app = FastAPI(title="Cloud Run Pub/Sub → Firestore Materializer", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    project_id = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCLOUD_PROJECT")
    if not project_id:
        raise RuntimeError("Missing GCP_PROJECT (or GOOGLE_CLOUD_PROJECT).")

    database = os.getenv("FIRESTORE_DATABASE") or "(default)"
    app.state.firestore_writer = FirestoreWriter(project_id=project_id, database=database)
    app.state.loop_heartbeat_monotonic = time.monotonic()

    log(
        "startup",
        severity="INFO",
        gcp_project=project_id,
        firestore_database=database,
        env=os.getenv("ENV") or "unknown",
        default_region=os.getenv("DEFAULT_REGION") or "unknown",
        system_events_topic=os.getenv("SYSTEM_EVENTS_TOPIC") or "",
        subscription_topic_map=bool((os.getenv("SUBSCRIPTION_TOPIC_MAP") or "").strip()),
    )


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
    """
    Pub/Sub push handler for Cloud Run.

    Required behavior:
    - validate + decode base64 JSON payload
    - idempotency via messageId -> ops_dedupe/{messageId}
    - stale protection for ops_services/{serviceId}
    - structured JSON logs
    """
    app.state.loop_heartbeat_monotonic = time.monotonic()

    try:
        body = await req.json()
    except Exception as e:
        log("pubsub.invalid_json", severity="ERROR", error=str(e))
        raise HTTPException(status_code=400, detail="invalid_json") from e

    if not isinstance(body, dict):
        log("pubsub.invalid_envelope", severity="ERROR", reason="body_not_object")
        raise HTTPException(status_code=400, detail="invalid_envelope")

    subscription = body.get("subscription")
    subscription_str = str(subscription).strip() if subscription is not None else ""

    message = body.get("message")
    if not isinstance(message, dict):
        log("pubsub.invalid_envelope", severity="ERROR", reason="missing_message")
        raise HTTPException(status_code=400, detail="invalid_envelope")

    message_id = str(message.get("messageId") or "").strip()
    if not message_id:
        log("pubsub.invalid_envelope", severity="ERROR", reason="missing_messageId")
        raise HTTPException(status_code=400, detail="missing_messageId")

    delivery_attempt = None
    da = message.get("deliveryAttempt")
    if da is not None:
        try:
            delivery_attempt = int(da)
        except Exception:
            delivery_attempt = None

    publish_time = _parse_rfc3339(message.get("publishTime")) or _utc_now()
    attributes_raw = message.get("attributes") or {}
    attributes: dict[str, str] = {}
    if isinstance(attributes_raw, dict):
        for k, v in attributes_raw.items():
            if k is None:
                continue
            attributes[str(k)] = "" if v is None else str(v)

    writer: FirestoreWriter = app.state.firestore_writer
    dlq_sample_rate = _float_env("DLQ_SAMPLE_RATE", default=DLQ_SAMPLE_RATE_DEFAULT)
    dlq_sample_ttl_hours = _float_env("DLQ_SAMPLE_TTL_HOURS", default=DLQ_SAMPLE_TTL_HOURS_DEFAULT)

    def _record_dlq_candidate(*, reason: str, error: str, handler_name: str, topic: str, payload: Optional[dict[str, Any]]) -> None:
        # "DLQ" is enforced by Pub/Sub dead-letter policy; we log + sample so we can debug without relying on DLQ retention.
        log(
            "pubsub.dlq_candidate",
            severity="ERROR",
            messageId=message_id,
            subscription=subscription_str,
            topic=topic or "",
            handler=handler_name,
            reason=reason,
            error=error,
            http_status=400,
            deliveryAttempt=delivery_attempt,
            dlq_sample_rate=dlq_sample_rate,
        )
        wrote = writer.maybe_write_sampled_dlq_event(
            message_id=message_id,
            subscription=subscription_str,
            topic=topic or "",
            handler=handler_name,
            http_status=400,
            reason=reason,
            error=error,
            delivery_attempt=delivery_attempt,
            attributes=attributes,
            payload=payload,
            sample_rate=dlq_sample_rate,
            ttl_hours=dlq_sample_ttl_hours,
        )
        if wrote:
            log(
                "pubsub.dlq_sample_written",
                severity="NOTICE",
                messageId=message_id,
                subscription=subscription_str,
                handler=handler_name,
                deliveryAttempt=delivery_attempt,
            )

    data_b64 = message.get("data")
    if not isinstance(data_b64, str) or not data_b64.strip():
        _record_dlq_candidate(reason="missing_data", error="missing_data", handler_name="unknown", topic="", payload=None)
        raise HTTPException(status_code=400, detail="missing_data")

    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception as e:
        _record_dlq_candidate(reason="invalid_base64", error=str(e), handler_name="unknown", topic="", payload=None)
        raise HTTPException(status_code=400, detail="invalid_base64") from e

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        _record_dlq_candidate(reason="invalid_payload_json", error=str(e), handler_name="unknown", topic="", payload=None)
        raise HTTPException(status_code=400, detail="invalid_payload_json") from e

    if not isinstance(payload, dict):
        _record_dlq_candidate(
            reason="payload_not_object",
            error=f"payloadType={type(payload).__name__}",
            handler_name="unknown",
            topic="",
            payload=None,
        )
        raise HTTPException(status_code=400, detail="payload_not_object")

    inferred_topic = infer_topic(attributes=attributes, payload=payload, subscription=subscription_str)
    handler = route_payload(payload=payload, attributes=attributes, topic=inferred_topic)
    if handler is None:
        _record_dlq_candidate(
            reason="unroutable_payload",
            error="no_route_match",
            handler_name="unknown",
            topic=inferred_topic or "",
            payload=payload,
        )
        raise HTTPException(status_code=400, detail="unroutable_payload")

    env = os.getenv("ENV") or "unknown"
    default_region = os.getenv("DEFAULT_REGION") or "unknown"
    if handler.name == "system_events":
        source_topic = os.getenv("SYSTEM_EVENTS_TOPIC") or ""
        if not source_topic:
            log("config.missing_system_events_topic", severity="ERROR")
            raise HTTPException(status_code=500, detail="missing_SYSTEM_EVENTS_TOPIC")
    else:
        # For non-system streams, prefer the inferred topic (from attributes/payload/subscription mapping).
        source_topic = inferred_topic or ""

    try:
        result = handler.handler(
            payload=payload,
            env=env,
            default_region=default_region,
            source_topic=source_topic,
            message_id=message_id,
            pubsub_published_at=publish_time,
            firestore_writer=writer,
        )
        log(
            "materialize.ok",
            severity="INFO",
            handler=handler.name,
            messageId=message_id,
            topic=source_topic,
            subscription=subscription_str,
            serviceId=result.get("serviceId"),
            applied=result.get("applied"),
            reason=result.get("reason"),
        )
        return {"ok": True, **result}
    except ValueError as e:
        # Treat as poison for this consumer; allow DLQ routing.
        _record_dlq_candidate(reason="materialize.bad_event", error=str(e), handler_name=handler.name, topic=source_topic, payload=payload)
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log(
            "materialize.exception",
            severity="ERROR",
            error=str(e),
            handler=handler.name,
            messageId=message_id,
            subscription=subscription_str,
            topic=source_topic,
            deliveryAttempt=delivery_attempt,
        )
        raise HTTPException(status_code=500, detail="materialize_exception") from e


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT") or "8080")
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="warning", access_log=False)

