"""
Cloud Run Pub/Sub → Firestore materializer (push subscription).

Contract Unification Gate:
- Validate topic-specific canonical schemas from `contracts/` before processing.
- If invalid: record (DLQ sample / ops alert), log structured error, and ACK (2xx).
"""

from __future__ import annotations

import base64
import json
import os
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from fastapi import FastAPI, HTTPException, Request, Response

from backend.common.logging import init_structured_logging
from backend.common.logging import install_fastapi_request_id_middleware
from backend.common.logging import log_standard_event
from backend.observability.correlation import bind_correlation_id, get_or_create_correlation_id

from backend.contracts.ops_alerts import try_write_contract_violation_alert
from backend.contracts.registry import validate_topic_event
from event_utils import infer_topic
from firestore_writer import FirestoreWriter
from schema_router import route_payload
from time_audit import ensure_utc


SERVICE_NAME = "cloudrun-pubsub-firestore-materializer"
DLQ_SAMPLE_RATE_DEFAULT = "0.01"
DLQ_SAMPLE_TTL_HOURS_DEFAULT = "72"

# Emit structured JSON to stdout (Cloud Run will ingest as jsonPayload).
init_structured_logging(service=SERVICE_NAME, env=os.getenv("ENV") or "unknown", level=os.getenv("LOG_LEVEL") or "INFO")
_logger = logging.getLogger("cloudrun_consumer")


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
    try:
        correlation_id = fields.pop("correlation_id", None)
        event_id = fields.pop("event_id", None)
        topic = fields.pop("topic", None)
        outcome = fields.pop("outcome", None)
        latency_ms = fields.pop("latency_ms", None)

        log_standard_event(
            _logger,
            str(event_type),
            severity=str(severity).upper(),
            correlation_id=str(correlation_id) if correlation_id is not None else None,
            event_id=str(event_id) if event_id is not None else None,
            topic=str(topic) if topic is not None else None,
            outcome=str(outcome) if outcome is not None else None,
            latency_ms=latency_ms,
            **fields,
        )
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


def _validate_required_env(required: list[str]) -> None:
    presence = {name: bool((os.getenv(name) or "").strip()) for name in required}
    log("config.env_validation", severity="INFO", outcome="success", required_env=presence)
    missing = [name for name, ok in presence.items() if not ok]
    if missing:
        log("config.env_missing", severity="CRITICAL", outcome="failure", missing_env=missing)
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


app = FastAPI(title="Cloud Run Pub/Sub → Firestore Materializer", version="0.1.0")
install_fastapi_request_id_middleware(app, service=SERVICE_NAME)


@app.on_event("startup")
async def _startup() -> None:
    project_id = (os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project_id:
        raise RuntimeError("Missing required env var: GCP_PROJECT (or GOOGLE_CLOUD_PROJECT)")
    database = os.getenv("FIRESTORE_DATABASE") or "(default)"
    collection_prefix = os.getenv("FIRESTORE_COLLECTION_PREFIX") or ""
    app.state.firestore_writer = FirestoreWriter(project_id=project_id, database=database, collection_prefix=collection_prefix)
    app.state.loop_heartbeat_monotonic = time.monotonic()

    log(
        "startup",
        severity="INFO",
        outcome="success",
        has_gcp_project=True,
        has_system_events_topic=True,
        has_ingest_flag_secret_id=True,
        has_env=True,
        firestore_database=database,
        firestore_collection_prefix=collection_prefix,
        env=os.getenv("ENV") or "unknown",
        default_region=os.getenv("DEFAULT_REGION") or "unknown",
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
    app.state.loop_heartbeat_monotonic = time.monotonic()
    start_perf = time.perf_counter()

    def _latency_ms() -> int:
        return int(max(0.0, (time.perf_counter() - start_perf) * 1000.0))

    # Ensure the request has a correlation_id even before decoding the message.
    req_correlation_id = get_or_create_correlation_id(headers=dict(req.headers))

    try:
        _require_json_content_type(req)
    except HTTPException as e:
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=req_correlation_id,
            latency_ms=_latency_ms(),
            reason="invalid_headers",
            error=str(getattr(e, "detail", "")),
            messageId=None,
            publishTime=None,
            subscription=None,
        )
        raise

    try:
        body = await req.json()
    except Exception as e:
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=req_correlation_id,
            latency_ms=_latency_ms(),
            reason="invalid_json",
            error=str(e),
            messageId=None,
            publishTime=None,
            subscription=str(req.headers.get("x-goog-subscription") or req.headers.get("x-goog-subscription-name") or "").strip()
            or None,
        )
        raise HTTPException(status_code=400, detail="invalid_json") from e
    if not isinstance(body, dict):
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=req_correlation_id,
            latency_ms=_latency_ms(),
            reason="invalid_envelope",
            error="body_not_object",
            messageId=None,
            publishTime=None,
            subscription=None,
        )
        raise HTTPException(status_code=400, detail="invalid_envelope")

    subscription = body.get("subscription")
    subscription_str = str(subscription).strip() if subscription is not None else ""
    if not subscription_str:
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=req_correlation_id,
            latency_ms=_latency_ms(),
            reason="invalid_envelope",
            error="missing_subscription",
            messageId=None,
            publishTime=None,
            subscription="",
        )
        raise HTTPException(status_code=400, detail="missing_subscription")

    # Validate X-Goog-* headers if present (best-effort).
    try:
        hdr = _validate_pubsub_headers(req=req, subscription_from_body=subscription_str)
    except HTTPException as e:
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=req_correlation_id,
            latency_ms=_latency_ms(),
            reason="invalid_headers",
            error=str(getattr(e, "detail", "")),
            subscription=subscription_str,
        )
        raise

    message = body.get("message")
    if not isinstance(message, dict):
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=req_correlation_id,
            latency_ms=_latency_ms(),
            reason="invalid_envelope",
            error="missing_message",
            messageId=None,
            publishTime=None,
            subscription=subscription_str,
        )
        raise HTTPException(status_code=400, detail="invalid_envelope")

    message_id = str(msg.get("messageId") or "").strip()
    if not message_id:
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=req_correlation_id,
            latency_ms=_latency_ms(),
            reason="invalid_envelope",
            error="missing_messageId",
            messageId=None,
            publishTime=str(message.get("publishTime") or "").strip() or None,
            subscription=subscription_str,
        )
        raise HTTPException(status_code=400, detail="missing_messageId")

    publish_time_raw = str(message.get("publishTime") or "").strip() or None
    event_id = message_id
    correlation_id = req_correlation_id

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
            outcome="failure",
            correlation_id=correlation_id,
            event_id=event_id,
            latency_ms=_latency_ms(),
            messageId=message_id,
            subscription=subscription_str,
            topic=topic or "",
            handler=handler_name,
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
        if wrote:
            log(
                "pubsub.dlq_sample_written",
                severity="NOTICE",
                outcome="success",
                correlation_id=correlation_id,
                event_id=event_id,
                latency_ms=_latency_ms(),
                messageId=message_id,
                subscription=subscription_str,
                handler=handler_name,
                deliveryAttempt=delivery_attempt,
            )

    data_b64 = message.get("data")
    if not isinstance(data_b64, str) or not data_b64.strip():
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=correlation_id,
            event_id=event_id,
            latency_ms=_latency_ms(),
            reason="invalid_envelope",
            error="missing_data",
            messageId=message_id,
            publishTime=publish_time_raw,
            subscription=subscription_str,
        )
        raise HTTPException(status_code=400, detail="missing_data")

    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception as e:
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=correlation_id,
            event_id=event_id,
            latency_ms=_latency_ms(),
            reason="invalid_envelope",
            error=f"invalid_base64:{str(e)}",
            messageId=message_id,
            publishTime=publish_time_raw,
            subscription=subscription_str,
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
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=correlation_id,
            event_id=event_id,
            latency_ms=_latency_ms(),
            reason="invalid_payload_json",
            error=str(e),
            messageId=message_id,
            publishTime=publish_time_raw,
            subscription=subscription_str,
        )
        raise HTTPException(status_code=400, detail="invalid_payload_json") from e

    if not isinstance(payload, dict):
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=correlation_id,
            event_id=event_id,
            latency_ms=_latency_ms(),
            reason="payload_not_object",
            payloadType=str(type(payload).__name__),
            messageId=message_id,
            publishTime=publish_time_raw,
            subscription=subscription_str,
        )

    try:
        payload, envelope = _maybe_unwrap_event_envelope(payload)
    except ValueError as e:
        log(
            "pubsub.invalid_event_envelope",
            severity="ERROR",
            outcome="failure",
            correlation_id=correlation_id,
            event_id=event_id,
            latency_ms=_latency_ms(),
            error=str(e),
            messageId=message_id,
        )
        raise HTTPException(status_code=400, detail="invalid_event_envelope") from e

    # Promote stable identifiers from the decoded payload (when present).
    try:
        payload_event_id = payload.get("eventId")
        if payload_event_id is not None and str(payload_event_id).strip():
            event_id = str(payload_event_id).strip()
    except Exception:
        pass
    try:
        for k in ("correlation_id", "correlationId", "request_id", "requestId"):
            v = payload.get(k)
            if v is not None and str(v).strip():
                correlation_id = str(v).strip()
                break
        if not correlation_id:
            for k in ("correlation_id", "correlationId", "request_id", "requestId"):
                v = attributes.get(k)
                if v is not None and str(v).strip():
                    correlation_id = str(v).strip()
                    break
        if envelope is not None and isinstance(envelope, dict):
            for k in ("correlation_id", "correlationId", "request_id", "requestId"):
                v = envelope.get(k)
                if v is not None and str(v).strip():
                    correlation_id = str(v).strip()
                    break
    except Exception:
        pass

    inferred_topic = infer_topic(attributes=attributes, payload=payload, subscription=subscription_str)
    handler = route_payload(payload=payload, attributes=attributes, topic=inferred_topic)
    if handler is None:
        log(
            "pubsub.rejected",
            severity="ERROR",
            outcome="failure",
            correlation_id=correlation_id,
            event_id=event_id,
            latency_ms=_latency_ms(),
            reason="unroutable_payload",
            messageId=message_id,
            publishTime=publish_time_raw,
            subscription=subscription_str,
            topic=inferred_topic or "",
        )
        raise HTTPException(status_code=400, detail="unroutable_payload")

    env = os.getenv("ENV") or "unknown"
    default_region = os.getenv("DEFAULT_REGION") or "unknown"
    if handler.name == "system_events":
        # System events should be materializable even if SYSTEM_EVENTS_TOPIC isn't set,
        # since producers may be absent/misconfigured and we still want the consumer healthy.
        source_topic = (
            (os.getenv("SYSTEM_EVENTS_TOPIC") or "").strip()
            or (inferred_topic or "").strip()
            or (attributes.get("topic") or "").strip()
            or ""
        )
        if not source_topic:
            log(
                "config.missing_system_events_topic",
                severity="WARNING",
                outcome="degraded",
                correlation_id=correlation_id,
                event_id=event_id,
                latency_ms=_latency_ms(),
            )
    else:
        # For non-system streams, prefer the inferred topic (from attributes/payload/subscription mapping).
        source_topic = inferred_topic or ""

    writer: FirestoreWriter = app.state.firestore_writer
    replay_run_id = (os.getenv("REPLAY_RUN_ID") or "").strip() or None
    replay: ReplayContext | None = None
    if replay_run_id and source_topic:
        replay = ReplayContext(run_id=replay_run_id, consumer=SERVICE_NAME, topic=str(source_topic))

    with bind_correlation_id(correlation_id=correlation_id):
        try:
            # Visibility-only: detect duplicate deliveries (never gate processing).
            is_dup = writer.observe_pubsub_delivery(
                message_id=message_id,
                topic=source_topic,
                subscription=subscription_str,
                handler=handler.name,
                published_at=publish_time,
                delivery_attempt=delivery_attempt,
            )
            if is_dup is True:
                log(
                    "pubsub.duplicate_delivery_detected",
                    severity="WARNING",
                    outcome="duplicate",
                    correlation_id=correlation_id,
                    event_id=event_id,
                    latency_ms=_latency_ms(),
                    handler=handler.name,
                    messageId=message_id,
                    topic=source_topic,
                    subscription=subscription_str,
                    deliveryAttempt=delivery_attempt,
                    publishTime=publish_time.isoformat(),
                )

            result = handler.handler(
                payload=payload,
                env=env,
                default_region=default_region,
                source_topic=source_topic,
                message_id=message_id,
                pubsub_published_at=publish_time,
                firestore_writer=writer,
                replay=replay,
            )
            if replay is not None:
                try:
                    # Best-effort markers; never fail the message due to marker writes.
                    write_replay_marker(
                        db=writer._db,  # intentionally internal; minimal hook
                        replay=replay,
                        message_id=message_id,
                        pubsub_published_at=publish_time,
                        event_time=_parse_rfc3339(result.get("eventTime") or result.get("updatedAt")) or publish_time,
                        handler=handler.name,
                        applied=bool(result.get("applied")),
                        reason=str(result.get("reason") or ""),
                    )
                except Exception:
                    pass
            log(
                "materialize.ok",
                severity="INFO",
                outcome="success",
                correlation_id=correlation_id,
                event_id=event_id,
                latency_ms=_latency_ms(),
                handler=handler.name,
                messageId=message_id,
                **{"source.messageId": message_id},
                topic=source_topic,
                subscription=subscription_str,
                deliveryAttempt=delivery_attempt,
                serviceId=result.get("serviceId"),
                applied=result.get("applied"),
                reason=result.get("reason"),
                header_subscription=hdr.get("header_subscription"),
                header_topic=hdr.get("header_topic"),
            )
            if result.get("applied") is False and str(result.get("reason") or "") == "duplicate_message_noop":
                log(
                    "pubsub.duplicate_ignored",
                    severity="WARNING",
                    outcome="noop",
                    correlation_id=correlation_id,
                    event_id=event_id,
                    latency_ms=_latency_ms(),
                    handler=handler.name,
                    messageId=message_id,
                    topic=source_topic,
                    subscription=subscription_str,
                    deliveryAttempt=delivery_attempt,
                    kind=result.get("kind"),
                    entityId=result.get("serviceId") or result.get("docId"),
                    reason=result.get("reason"),
                )
            return {"ok": True, **result}
        except ValueError as e:
            # Treat as poison for this consumer; allow DLQ routing.
            log(
                "materialize.bad_event",
                severity="ERROR",
                outcome="failure",
                correlation_id=correlation_id,
                event_id=event_id,
                latency_ms=_latency_ms(),
                error=str(e),
                handler=handler.name,
                messageId=message_id,
                **{"source.messageId": message_id},
            )
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            log(
                "materialize.exception",
                severity="ERROR",
                outcome="failure",
                correlation_id=correlation_id,
                event_id=event_id,
                latency_ms=_latency_ms(),
                error=str(e),
                handler=handler.name,
                messageId=message_id,
                **{"source.messageId": message_id},
            )
            raise HTTPException(status_code=500, detail="materialize_exception") from e


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.getenv("PORT") or "8080")
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="warning", access_log=False)

