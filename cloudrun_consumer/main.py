"""
cloudrun_consumer entrypoint diagnostics

Runtime assumptions (documented for deploy/debug):
- This module is typically imported by `uvicorn` (e.g. `uvicorn main:app`) from the
  service working directory (or an image that places this file on `sys.path`).
- If you see import failures for sibling modules (e.g. `event_utils`), ensure the
  service directory is on `sys.path` (often via `PYTHONPATH`) and log `sys.path`
  to confirm.
"""

from __future__ import annotations

import base64
import json
import logging
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
from replay_support import ReplayContext, write_replay_marker
from schema_router import route_payload
from time_audit import ensure_utc

def _startup_diag(event_type: str, *, severity: str = "INFO", **fields: Any) -> None:
    """
    Print a structured JSON diagnostic log.

    Intended for early import/startup failures where the main logger may not be configured.
    """
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
        return ensure_utc(value, source="cloudrun_consumer.main._parse_rfc3339", field="datetime")
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return ensure_utc(dt, source="cloudrun_consumer.main._parse_rfc3339", field="iso_string")
    except Exception:
        log("time.parse_failed", severity="ERROR", value=s, exception=traceback.format_exc()[-8000:])
        return None


def _maybe_unwrap_event_envelope(payload: dict[str, Any]) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """
    Back-compat adapter:
    - If message.data is an EventEnvelope (v1), validate schemaVersion and unwrap to its `payload`.
    - Otherwise, treat message.data as payload-only (legacy producers).
    """
    # Heuristic: require both an envelope discriminator + a nested payload object.
    if not isinstance(payload.get("payload"), dict):
        return payload, None

    if not (
        isinstance(payload.get("event_type"), str)
        or isinstance(payload.get("eventType"), str)
        or isinstance(payload.get("agent_name"), str)
        or isinstance(payload.get("agentName"), str)
    ):
        return payload, None

    schema_v = payload.get("schemaVersion")
    if schema_v is None:
        schema_v = payload.get("schema_version")
    if schema_v is None:
        raise ValueError("missing_schemaVersion")

    try:
        sv_int = int(schema_v)
    except Exception as e:
        raise ValueError("invalid_schemaVersion") from e

    if sv_int != 1:
        raise ValueError(f"unsupported_schemaVersion:{sv_int}")

    inner = payload.get("payload")
    assert isinstance(inner, dict)  # guarded above

    # Preserve envelope timestamp for ordering if the payload doesn't already carry it.
    ts = payload.get("ts")
    if isinstance(ts, str) and ts.strip():
        inner.setdefault("producedAt", ts.strip())

    return inner, payload


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


def _require_json_content_type(req: Request) -> None:
    ct = str(req.headers.get("content-type") or "").strip()
    if ("\n" in ct) or ("\r" in ct):
        raise HTTPException(status_code=400, detail="invalid_header_value")
    if "application/json" not in ct.lower():
        raise HTTPException(status_code=415, detail="unsupported_media_type")


def _validate_pubsub_headers(*, req: Request, subscription_from_body: str) -> dict[str, Optional[str]]:
    """
    Best-effort Pub/Sub push header validation.

    - Enforce JSON content type.
    - If X-Goog-* headers are present, validate they are well-formed.
    - If X-Goog-Subscription is present, require it matches body.subscription (full or short name).

    No authentication decisions are made here.
    """
    _require_json_content_type(req)

    x_sub = str(req.headers.get("x-goog-subscription") or req.headers.get("x-goog-subscription-name") or "").strip()
    x_topic = str(req.headers.get("x-goog-topic") or "").strip()

    for v in (x_sub, x_topic):
        if ("\n" in v) or ("\r" in v):
            raise HTTPException(status_code=400, detail="invalid_header_value")

    if x_topic and (not x_topic.startswith("projects/") or "/topics/" not in x_topic):
        raise HTTPException(status_code=400, detail="invalid_x_goog_topic")

    if x_sub:
        body_short = subscription_from_body.split("/subscriptions/")[-1]
        hdr_short = x_sub.split("/subscriptions/")[-1]
        if subscription_from_body and (subscription_from_body != x_sub) and (body_short != hdr_short):
            raise HTTPException(status_code=400, detail="subscription_header_mismatch")

    return {"header_subscription": x_sub or None, "header_topic": x_topic or None}


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


def _normalize_env_alias(target: str, aliases: list[str]) -> None:
    """
    Ensures `target` is present by copying from the first present alias.
    Logs nothing and never exposes values.
    """
    v = os.getenv(target)
    if v is not None and str(v).strip():
        return
    for a in aliases:
        av = os.getenv(a)
        if av is not None and str(av).strip():
            os.environ[target] = str(av).strip()
            return


def _validate_required_env(required: list[str]) -> None:
    presence = {name: bool((os.getenv(name) or "").strip()) for name in required}
    log("config.env_validation", severity="INFO", required_env=presence)
    missing = [name for name, ok in presence.items() if not ok]
    if missing:
        log("config.env_missing", severity="CRITICAL", missing_env=missing)
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")


app = FastAPI(title="Cloud Run Pub/Sub → Firestore Materializer", version="0.1.0")


@app.on_event("startup")
async def _startup() -> None:
    _normalize_env_alias("GCP_PROJECT", ["GOOGLE_CLOUD_PROJECT", "GCLOUD_PROJECT", "GCP_PROJECT_ID", "PROJECT_ID"])
    _validate_required_env(["GCP_PROJECT", "SYSTEM_EVENTS_TOPIC", "INGEST_FLAG_SECRET_ID", "ENV"])

    project_id = _require_env("GCP_PROJECT")

    database = os.getenv("FIRESTORE_DATABASE") or "(default)"
    collection_prefix = os.getenv("FIRESTORE_COLLECTION_PREFIX") or ""
    app.state.firestore_writer = FirestoreWriter(project_id=project_id, database=database, collection_prefix=collection_prefix)
    app.state.loop_heartbeat_monotonic = time.monotonic()

    log(
        "startup",
        severity="INFO",
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
        _require_json_content_type(req)
    except HTTPException as e:
        log(
            "pubsub.rejected",
            severity="ERROR",
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
            reason="invalid_envelope",
            error="missing_subscription",
            messageId=None,
            publishTime=None,
            subscription="",
        )
        raise HTTPException(status_code=400, detail="missing_subscription")

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

    message_id = str(message.get("messageId") or "").strip()
    if not message_id:
        log(
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_envelope",
            error="missing_messageId",
            messageId=None,
            publishTime=str(message.get("publishTime") or "").strip() or None,
            subscription=subscription_str,
        )
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
        log(
            "pubsub.rejected",
            severity="ERROR",
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
            reason="invalid_envelope",
            error=f"invalid_base64:{str(e)}",
            messageId=message_id,
            publishTime=publish_time_raw,
            subscription=subscription_str,
        )
        raise HTTPException(status_code=400, detail="invalid_base64") from e

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as e:
        log(
            "pubsub.rejected",
            severity="ERROR",
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
            reason="payload_not_object",
            payloadType=str(type(payload).__name__),
            messageId=message_id,
            publishTime=publish_time_raw,
            subscription=subscription_str,
        )
        raise HTTPException(status_code=400, detail="payload_not_object")

    try:
        payload, envelope = _maybe_unwrap_event_envelope(payload)
    except ValueError as e:
        log("pubsub.invalid_event_envelope", severity="ERROR", error=str(e), messageId=message_id)
        raise HTTPException(status_code=400, detail="invalid_event_envelope") from e

    inferred_topic = infer_topic(attributes=attributes, payload=payload, subscription=subscription_str)
    handler = route_payload(payload=payload, attributes=attributes, topic=inferred_topic)
    if handler is None:
        log(
            "pubsub.rejected",
            severity="ERROR",
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
            log("config.missing_system_events_topic", severity="WARNING")
    else:
        # For non-system streams, prefer the inferred topic (from attributes/payload/subscription mapping).
        source_topic = inferred_topic or ""

    writer: FirestoreWriter = app.state.firestore_writer
    replay_run_id = (os.getenv("REPLAY_RUN_ID") or "").strip() or None
    replay: ReplayContext | None = None
    if replay_run_id and source_topic:
        replay = ReplayContext(run_id=replay_run_id, consumer=SERVICE_NAME, topic=str(source_topic))

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
            error=str(e),
            handler=handler.name,
            messageId=message_id,
            **{"source.messageId": message_id},
        )
        raise HTTPException(status_code=500, detail="materialize_exception") from e


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT") or "8080")
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="warning", access_log=False)

