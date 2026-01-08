"""
Cloud Run Pub/Sub → Firestore materializer (push subscription).

Contract Unification Gate:
- Validate topic-specific canonical schemas from `contracts/` before processing.
- If invalid: record (DLQ sample / ops alert), log structured error, and ACK (2xx).
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import logging
import random
import traceback
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response

from backend.contracts.ops_alerts import try_write_contract_violation_alert
from backend.contracts.registry import validate_topic_event
from event_utils import infer_topic
from firestore_writer import FirestoreWriter
from schema_router import route_payload
from time_audit import ensure_utc


SERVICE_NAME = "cloudrun-pubsub-firestore-materializer"
DLQ_SAMPLE_RATE_DEFAULT = "0.01"
DLQ_SAMPLE_TTL_HOURS_DEFAULT = "72"

CONSUMER_MAX_WORKERS_DEFAULT = "8"
CONSUMER_QUEUE_SIZE_DEFAULT = "64"

FIRESTORE_RETRY_MAX_ATTEMPTS_DEFAULT = "6"
FIRESTORE_RETRY_INITIAL_BACKOFF_S_DEFAULT = "0.25"
FIRESTORE_RETRY_MAX_BACKOFF_S_DEFAULT = "6.0"
FIRESTORE_RETRY_MAX_TOTAL_S_DEFAULT = "8.0"

DLQ_PUBLISH_DEADLINE_S_DEFAULT = "10.0"

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


def _process_item_once_sync(item: _WorkItem) -> dict[str, Any]:
    """
    Executes the actual materialization work (runs in a worker thread).
    """
    writer: FirestoreWriter = app.state.firestore_writer

    # Visibility-only: detect duplicate deliveries (never gate processing).
    try:
        is_dup = writer.observe_pubsub_delivery(
            message_id=item.message_id,
            topic=item.source_topic,
            subscription=item.subscription,
            handler=item.handler_name,
            published_at=item.publish_time,
            delivery_attempt=item.delivery_attempt,
        )
        if is_dup is True:
            log(
                "pubsub.duplicate_delivery_detected",
                severity="WARNING",
                handler=item.handler_name,
                messageId=item.message_id,
                topic=item.source_topic,
                subscription=item.subscription,
                deliveryAttempt=item.delivery_attempt,
                publishTime=item.publish_time.isoformat(),
            )
    except Exception:
        # Never fail the message due to visibility-only writes.
        pass

    handler_fn = item.handler_fn
    return handler_fn(
        payload=item.payload,
        env=item.env,
        default_region=item.default_region,
        source_topic=item.source_topic,
        message_id=item.message_id,
        pubsub_published_at=item.publish_time,
        firestore_writer=writer,
        replay=item.replay,
    )


def _process_item_with_retry_sync(item: _WorkItem) -> dict[str, Any]:
    """
    Retries transient Firestore errors with exponential backoff.
    Raises `_PermanentFirestoreError` on permanent Firestore permission/validation failures.
    """
    max_attempts = max(1, _int_env("FIRESTORE_RETRY_MAX_ATTEMPTS", default=FIRESTORE_RETRY_MAX_ATTEMPTS_DEFAULT))
    initial_backoff_s = max(0.0, _float_env("FIRESTORE_RETRY_INITIAL_BACKOFF_S", default=FIRESTORE_RETRY_INITIAL_BACKOFF_S_DEFAULT))
    max_backoff_s = max(0.0, _float_env("FIRESTORE_RETRY_MAX_BACKOFF_S", default=FIRESTORE_RETRY_MAX_BACKOFF_S_DEFAULT))
    max_total_s = max(0.0, _float_env("FIRESTORE_RETRY_MAX_TOTAL_S", default=FIRESTORE_RETRY_MAX_TOTAL_S_DEFAULT))

    started = time.monotonic()
    last_exc: Optional[BaseException] = None

    for attempt in range(1, max_attempts + 1):
        try:
            return _process_item_once_sync(item)
        except ValueError:
            # "Poison" events should not be retried by us (Pub/Sub DLQ policy can handle).
            raise
        except Exception as e:
            last_exc = e
            if _is_permanent_firestore_error(e):
                raise _PermanentFirestoreError(str(e)) from e

            transient = _is_transient_firestore_error(e)
            elapsed_s = time.monotonic() - started
            if (not transient) or attempt >= max_attempts or (max_total_s > 0.0 and elapsed_s >= max_total_s):
                raise

            sleep_s = _sleep_backoff(attempt=attempt, initial_backoff_s=initial_backoff_s, max_backoff_s=max_backoff_s)
            log(
                "firestore.retry",
                severity="WARNING",
                messageId=item.message_id,
                topic=item.source_topic,
                handler=item.handler_name,
                attempt=attempt,
                max_attempts=max_attempts,
                sleep_s=sleep_s,
                error_type=e.__class__.__name__,
                error_code=_exc_code(e),
                error=str(e),
            )

    # Defensive: should be unreachable due to raise/return in loop.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("firestore retry failed without exception")


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


def _int_env(name: str, *, default: str) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        raw = default
    try:
        return int(raw)
    except Exception:
        try:
            return int(default)
        except Exception:
            return 0


def _exc_code(exc: BaseException) -> str:
    """
    Best-effort extraction of a stable Google/gRPC error code string.
    """
    try:
        code = getattr(exc, "code", None)
        if callable(code):
            code = code()
        if code is None:
            return ""
        # grpc.StatusCode has a `.name`
        name = getattr(code, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip().upper()
        return str(code).strip().upper()
    except Exception:
        return ""


def _is_transient_firestore_error(exc: BaseException) -> bool:
    code = _exc_code(exc)
    if code in {"UNAVAILABLE", "DEADLINE_EXCEEDED", "ABORTED", "INTERNAL", "RESOURCE_EXHAUSTED", "UNKNOWN"}:
        return True
    if code in {"PERMISSION_DENIED", "INVALID_ARGUMENT"}:
        return False

    name = exc.__class__.__name__
    if name in {"ServiceUnavailable", "DeadlineExceeded", "InternalServerError", "Aborted", "ResourceExhausted", "Unknown"}:
        return True
    if name in {"PermissionDenied", "InvalidArgument", "Unauthenticated"}:
        return False
    return False


def _is_permanent_firestore_error(exc: BaseException) -> bool:
    code = _exc_code(exc)
    if code in {"PERMISSION_DENIED", "INVALID_ARGUMENT"}:
        return True
    name = exc.__class__.__name__
    if name in {"PermissionDenied", "InvalidArgument"}:
        return True
    return False


def _sleep_backoff(*, attempt: int, initial_backoff_s: float, max_backoff_s: float) -> float:
    base = initial_backoff_s * (2 ** max(0, attempt - 1))
    backoff = min(max_backoff_s, base)
    sleep_s = backoff * random.uniform(0.5, 1.5)
    time.sleep(max(0.0, sleep_s))
    return sleep_s


class _PermanentFirestoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class _WorkItem:
    message_id: str
    subscription: str
    source_topic: str
    handler_name: str
    handler_fn: Any
    payload: dict[str, Any]
    attributes: dict[str, str]
    publish_time: datetime
    delivery_attempt: Optional[int]
    env: str
    default_region: str
    replay: ReplayContext | None


class _WorkQueueFull(Exception):
    pass


class _WorkQueue:
    def __init__(self, *, workers: int, queue_size: int) -> None:
        self._queue: asyncio.Queue[tuple[_WorkItem, asyncio.Future[dict[str, Any]]]] = asyncio.Queue(
            maxsize=max(0, int(queue_size))
        )
        self._workers: list[asyncio.Task[None]] = []
        self._workers_n = max(1, int(workers))

    def start(self) -> None:
        if self._workers:
            return
        for i in range(self._workers_n):
            self._workers.append(asyncio.create_task(self._worker_loop(i)))

    async def submit(self, item: _WorkItem) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        try:
            self._queue.put_nowait((item, fut))
        except asyncio.QueueFull as e:
            raise _WorkQueueFull() from e
        return await fut

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            item, fut = await self._queue.get()
            try:
                app.state.loop_heartbeat_monotonic = time.monotonic()
                result = await asyncio.to_thread(_process_item_with_retry_sync, item)
                if not fut.done():
                    fut.set_result(result)
            except Exception as e:
                if not fut.done():
                    fut.set_exception(e)
            finally:
                self._queue.task_done()


class _DlqPublisher:
    def __init__(self, *, project_id: str, topic: str) -> None:
        try:
            from google.cloud import pubsub_v1  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("google-cloud-pubsub is required for explicit DLQ publishing") from e

        self._client = pubsub_v1.PublisherClient()
        t = str(topic or "").strip()
        if t.startswith("projects/") and "/topics/" in t:
            self._topic_path = t
        else:
            self._topic_path = self._client.topic_path(str(project_id), t)

    def publish_json(self, *, payload: dict[str, Any], attributes: Optional[dict[str, str]] = None, timeout_s: float) -> str:
        attrs = attributes or {}
        data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        future = self._client.publish(self._topic_path, data, **{k: str(v) for k, v in attrs.items()})
        return str(future.result(timeout=max(0.1, float(timeout_s))))


def _normalize_env_alias(target: str, aliases: list[str]) -> None:
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
    project_id = (os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    if not project_id:
        raise RuntimeError("Missing required env var: GCP_PROJECT (or GOOGLE_CLOUD_PROJECT)")
    database = os.getenv("FIRESTORE_DATABASE") or "(default)"
    collection_prefix = os.getenv("FIRESTORE_COLLECTION_PREFIX") or ""
    app.state.firestore_writer = FirestoreWriter(project_id=project_id, database=database, collection_prefix=collection_prefix)
    app.state.loop_heartbeat_monotonic = time.monotonic()

    app.state.work_queue = _WorkQueue(
        workers=_int_env("CONSUMER_MAX_WORKERS", default=CONSUMER_MAX_WORKERS_DEFAULT),
        queue_size=_int_env("CONSUMER_QUEUE_SIZE", default=CONSUMER_QUEUE_SIZE_DEFAULT),
    )
    app.state.work_queue.start()

    dlq_topic = (os.getenv("DLQ_TOPIC") or "").strip()
    if dlq_topic:
        app.state.dlq_publisher = _DlqPublisher(project_id=project_id, topic=dlq_topic)
        log("dlq.publisher_configured", severity="INFO", dlq_topic=dlq_topic)
    else:
        app.state.dlq_publisher = None

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
        consumer_max_workers=_int_env("CONSUMER_MAX_WORKERS", default=CONSUMER_MAX_WORKERS_DEFAULT),
        consumer_queue_size=_int_env("CONSUMER_QUEUE_SIZE", default=CONSUMER_QUEUE_SIZE_DEFAULT),
        dlq_topic_configured=bool(dlq_topic),
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

    # Best-effort Pub/Sub push header validation (now that we know the subscription name).
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

    publish_time_raw = str(message.get("publishTime") or "").strip() or None

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
        # Backpressure: bound per-instance Firestore / CPU concurrency.
        work_queue: _WorkQueue = app.state.work_queue
        item = _WorkItem(
            message_id=message_id,
            subscription=subscription_str,
            source_topic=source_topic,
            handler_name=handler.name,
            handler_fn=handler.handler,
            payload=payload,
            attributes=attributes,
            publish_time=publish_time,
            delivery_attempt=delivery_attempt,
            env=env,
            default_region=default_region,
            replay=replay,
        )
        try:
            result = await work_queue.submit(item)
        except _WorkQueueFull:
            # Signal Pub/Sub to retry later (do not ack).
            log(
                "pubsub.backpressure",
                severity="WARNING",
                reason="queue_full",
                messageId=message_id,
                subscription=subscription_str,
                topic=source_topic,
                handler=handler.name,
                deliveryAttempt=delivery_attempt,
            )
            raise HTTPException(status_code=429, detail="backpressure_queue_full")

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
            topic=topic,
            subscription=subscription,
            messageId=message_id,
            applied=res.get("applied"),
            reason=res.get("reason"),
        )
        return {"ok": True, **res}
    except ValueError as e:
        # Treat as poison for this consumer; allow DLQ routing.
        _record_dlq_candidate(
            reason="value_error",
            error=str(e),
            handler_name=handler.name,
            topic=source_topic,
            payload=payload,
        )
        log(
            "materialize.bad_event",
            severity="ERROR",
            error=str(e),
            handler=handler.name,
            messageId=message_id,
            **{"source.messageId": message_id},
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except _PermanentFirestoreError as e:
        # Permanent Firestore failures should not loop forever.
        # Publish to an explicit DLQ (if configured) + emit an alertable log, then ACK (2xx).
        cause = getattr(e, "__cause__", None) or e
        code = _exc_code(cause)

        dlq_pub: Optional[_DlqPublisher] = getattr(app.state, "dlq_publisher", None)
        dlq_topic = (os.getenv("DLQ_TOPIC") or "").strip()

        dlq_payload = {
            "service": SERVICE_NAME,
            "env": os.getenv("ENV") or "unknown",
            "firestoreCode": code,
            "errorType": cause.__class__.__name__,
            "error": str(cause),
            "messageId": message_id,
            "subscription": subscription_str,
            "topic": source_topic,
            "handler": handler.name,
            "deliveryAttempt": delivery_attempt,
            "publishTime": publish_time.isoformat(),
            "attributes": attributes,
            "payload": payload,
        }
        published_id: Optional[str] = None
        if dlq_pub is not None and dlq_topic:
            try:
                published_id = dlq_pub.publish_json(
                    payload=dlq_payload,
                    attributes={"source": "cloudrun_consumer", "handler": handler.name, "firestoreCode": code},
                    timeout_s=_float_env("DLQ_PUBLISH_DEADLINE_S", default=DLQ_PUBLISH_DEADLINE_S_DEFAULT),
                )
            except Exception as pub_e:
                log(
                    "dlq.publish_failed",
                    severity="ERROR",
                    messageId=message_id,
                    topic=source_topic,
                    handler=handler.name,
                    error=str(pub_e),
                )

        log(
            "materialize.permanent_firestore_error",
            severity="ALERT",
            messageId=message_id,
            topic=source_topic,
            subscription=subscription_str,
            handler=handler.name,
            firestoreCode=code,
            dlq_topic=dlq_topic or None,
            dlq_message_id=published_id,
            error=str(cause),
        )
        return {"ok": False, "applied": False, "reason": "permanent_firestore_error", "dlqMessageId": published_id}
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
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="warning", access_log=False)

