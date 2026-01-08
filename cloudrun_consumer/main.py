from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from flask import Flask, Response, request
from google.cloud import firestore

from idempotency import IdempotencyStore
from schema_router import EventContext, SchemaRouter


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_rfc3339(s: str) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # record.msg is expected to already be JSON; fall back to wrapping.
        msg = record.getMessage()
        try:
            json.loads(msg)
            return msg
        except Exception:
            payload = {
                "severity": record.levelname,
                "message": msg,
            }
            return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("cloudrun_consumer")
    if logger.handlers:
        return logger

    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonLogFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


logger = _setup_logging()
app = Flask(__name__)


def _log(severity: str, message: str, **fields: Any) -> None:
    payload = {
        "severity": severity,
        "message": message,
        **fields,
    }
    line = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    getattr(logger, severity.lower(), logger.info)(line)


def _decode_pubsub_data(message: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    data_b64 = message.get("data")
    if not data_b64:
        return {}, None
    try:
        raw = base64.b64decode(data_b64).decode("utf-8")
    except Exception as e:
        return None, f"base64_decode_failed: {e}"
    raw = raw.strip()
    if not raw:
        return {}, None
    try:
        return json.loads(raw), None
    except Exception as e:
        return None, f"json_decode_failed: {e}"


def _extract_pubsub_envelope(body: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not isinstance(body, dict):
        return None, "invalid_body"
    message = body.get("message")
    if not isinstance(message, dict):
        return None, "missing_message"
    return message, None


@app.get("/healthz")
def healthz() -> Response:
    return Response("ok", status=200, mimetype="text/plain")


@app.post("/pubsub")
def pubsub_push() -> Response:
    received_at = _utc_now()
    try:
        body = request.get_json(force=True, silent=False)
    except Exception as e:
        _log("ERROR", "request_json_parse_failed", error=str(e))
        # Non-2xx will retry; malformed requests should be acknowledged.
        return Response(status=204)

    message, err = _extract_pubsub_envelope(body)
    if err:
        _log("ERROR", "invalid_pubsub_envelope", error=err, bodyType=str(type(body)))
        return Response(status=204)

    attributes = message.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {}
    # Pub/Sub attributes are string:string
    attributes = {str(k): str(v) for k, v in attributes.items()}

    message_id = str(message.get("messageId") or message.get("message_id") or "").strip()
    publish_time = str(message.get("publishTime") or "").strip()
    subscription = str((body.get("subscription") or "")).strip()

    payload, payload_err = _decode_pubsub_data(message)
    if payload_err:
        _log(
            "ERROR",
            "pubsub_message_decode_failed",
            error=payload_err,
            messageId=message_id,
            subscription=subscription,
        )
        return Response(status=204)
    if payload is None:
        return Response(status=204)

    router = SchemaRouter()
    topic = router.resolve_topic(subscription=subscription, attributes=attributes, payload=payload)
    event_type = router.resolve_event_type(attributes=attributes, payload=payload)

    schema_version = str(attributes.get("schemaVersion") or payload.get("schemaVersion") or "unknown")
    if schema_version not in router.supported_versions:
        _log(
            "WARNING",
            "unsupported_schema_version",
            messageId=message_id,
            schemaVersion=schema_version,
            supported=list(sorted(router.supported_versions)),
            topic=topic,
            eventType=event_type,
        )
        # Ack: unsupported schemas are not recoverable by retry.
        return Response(status=204)

    published_at = (
        _parse_rfc3339(str(payload.get("publishedAt") or "")) or _parse_rfc3339(attributes.get("publishedAt", ""))
    )
    if published_at is None:
        published_at = _parse_rfc3339(publish_time) or received_at
    published_at_iso = _iso_utc(published_at)

    if not message_id:
        # messageId missing shouldn't happen; still handle safely by using a deterministic fallback.
        message_id = f"missing:{subscription}:{published_at_iso}:{event_type}"

    # Enforce idempotency using messageId.
    db = firestore.Client()
    idempotency = IdempotencyStore(client=db)
    claim = idempotency.begin(
        message_id=message_id,
        published_at=published_at,
        extra={"topic": topic, "eventType": event_type, "subscription": subscription},
    )
    if claim.already_done:
        _log(
            "INFO",
            "duplicate_message_skipped",
            messageId=message_id,
            topic=topic,
            eventType=event_type,
            subscription=subscription,
        )
        return Response(status=204)

    handler = router.handler_for(topic=topic, event_type=event_type, payload=payload)
    if handler is None:
        _log(
            "WARNING",
            "no_handler_for_event",
            messageId=message_id,
            topic=topic,
            eventType=event_type,
            schemaVersion=schema_version,
        )
        return Response(status=204)

    ctx = EventContext(
        message_id=message_id,
        topic=topic,
        schema_version=schema_version,
        published_at_iso=published_at_iso,
        event_type=event_type,
        subscription=subscription,
        attributes=attributes,
    )

    try:
        handler(payload, ctx)
    except Exception as e:
        _log(
            "ERROR",
            "handler_failed",
            error=str(e),
            messageId=message_id,
            topic=topic,
            eventType=event_type,
        )
        # Non-2xx triggers Pub/Sub retry (safe because we only dedupe after status=done).
        return Response(status=500)

    idempotency.mark_done(message_id=message_id, extra={"topic": topic, "eventType": event_type})
    _log(
        "INFO",
        "event_processed",
        messageId=message_id,
        topic=topic,
        eventType=event_type,
        schemaVersion=schema_version,
        publishedAt=published_at_iso,
    )
    return Response(status=204)


if __name__ == "__main__":
    # Local dev only (Cloud Run uses gunicorn).
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
