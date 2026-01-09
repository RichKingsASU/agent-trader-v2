"""
cloudrun_consumer entrypoint diagnostics

Runtime assumptions (documented for deploy/debug):
- Containers should follow the canonical repo layout:
  - COPY . /app
  - PYTHONPATH=/app
  - use absolute imports (e.g. `from cloudrun_consumer...`)
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import os
import logging
import random
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request, Response

from backend.common.logging import init_structured_logging
from backend.common.logging import install_fastapi_request_id_middleware
from backend.common.logging import log_standard_event
from backend.observability.correlation import bind_correlation_id, get_or_create_correlation_id

from backend.contracts.ops_alerts import try_write_contract_violation_alert
from backend.contracts.registry import validate_topic_event

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
    Ensure `target` env var is set using first available alias.

    This service historically used multiple env var names across deploy targets.
    We normalize at startup so downstream code can rely on a single canonical key.
    """
    t = str(target or "").strip()
    if not t:
        return
    if (os.getenv(t) or "").strip():
        return
    for a in aliases or []:
        av = os.getenv(str(a))
        if av is not None and str(av).strip():
            os.environ[t] = str(av).strip()
            return


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
    """
    Pub/Sub push handler (Cloud Run).

    Ack semantics:
    - Return 2xx only when the message has been safely handled (including dedupe/no-op).
    - Return 5xx for retryable/transient errors.
    - Return 4xx for poison/permanent errors (compatible with Pub/Sub DLQ policies).
    """
    app.state.loop_heartbeat_monotonic = time.monotonic()
    started = time.perf_counter()

    def _latency_ms() -> int:
        return int(max(0.0, (time.perf_counter() - started) * 1000.0))

    req_correlation_id = get_or_create_correlation_id(headers=dict(req.headers))

    # Validate headers/content-type up front (no auth decisions).
    _require_json_content_type(req)

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
        )
        raise HTTPException(status_code=400, detail="invalid_json") from e

    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_envelope")

    subscription = str(body.get("subscription") or "").strip()
    if not subscription:
        raise HTTPException(status_code=400, detail="missing_subscription")

    hdr = _validate_pubsub_headers(req=req, subscription_from_body=subscription)

    message = body.get("message")
    if not isinstance(message, dict):
        raise HTTPException(status_code=400, detail="missing_message")

    message_id = str(message.get("messageId") or "").strip()
    if not message_id:
        raise HTTPException(status_code=400, detail="missing_messageId")

    publish_time_raw = str(message.get("publishTime") or "").strip()
    publish_time = _parse_rfc3339(publish_time_raw) or _utc_now()

    delivery_attempt: Optional[int] = None
    da_raw = message.get("deliveryAttempt")
    if isinstance(da_raw, int):
        delivery_attempt = da_raw
    else:
        try:
            if da_raw is not None and str(da_raw).strip():
                delivery_attempt = int(str(da_raw).strip())
        except Exception:
            delivery_attempt = None

    attributes: dict[str, str] = {}
    attrs_raw = message.get("attributes") or {}
    if isinstance(attrs_raw, dict):
        for k, v in attrs_raw.items():
            if k is None:
                continue
            attributes[str(k)] = "" if v is None else str(v)

    data_b64 = message.get("data")
    if not isinstance(data_b64, str) or not data_b64.strip():
        raise HTTPException(status_code=400, detail="missing_data")

    try:
        raw = base64.b64decode(data_b64, validate=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid_base64") from e

    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail="invalid_payload_json") from e

    # Unwrap EventEnvelopeV1 when present.
    envelope: Optional[dict[str, Any]] = decoded if isinstance(decoded, dict) else None
    payload_any: Any = decoded
    if isinstance(decoded, dict) and {"schemaVersion", "event_type", "agent_name", "git_sha", "ts", "trace_id", "payload"}.issubset(decoded.keys()):
        payload_any = decoded.get("payload")

    if not isinstance(payload_any, dict):
        raise HTTPException(status_code=400, detail="payload_not_object")

    payload: dict[str, Any] = payload_any
    correlation_id = req_correlation_id
    for k in ("correlation_id", "correlationId", "request_id", "requestId"):
        v = payload.get(k)
        if v is not None and str(v).strip():
            correlation_id = str(v).strip()
            break
    if envelope is not None:
        for k in ("trace_id", "traceId", "correlation_id", "correlationId"):
            v = envelope.get(k)
            if v is not None and str(v).strip():
                correlation_id = str(v).strip()
                break

    inferred_topic = infer_topic(attributes=attributes, payload=payload, subscription=subscription)
    routed = route_payload(payload=payload, attributes=attributes, topic=inferred_topic)
    if routed is None:
        raise HTTPException(status_code=400, detail="unroutable_payload")

    env = os.getenv("ENV") or "unknown"
    default_region = os.getenv("DEFAULT_REGION") or "unknown"

    if routed.name == "system_events":
        source_topic = (
            (os.getenv("SYSTEM_EVENTS_TOPIC") or "").strip()
            or (inferred_topic or "").strip()
            or (attributes.get("topic") or "").strip()
            or ""
        )
    else:
        source_topic = (inferred_topic or "").strip()

    replay_run_id = (os.getenv("REPLAY_RUN_ID") or "").strip() or None
    replay: ReplayContext | None = None
    if replay_run_id and source_topic:
        replay = ReplayContext(run_id=replay_run_id, consumer=SERVICE_NAME, topic=str(source_topic))

    writer: FirestoreWriter = app.state.firestore_writer

    with bind_correlation_id(correlation_id=correlation_id):
        try:
            result = routed.handler(
                payload=payload,
                env=env,
                default_region=default_region,
                source_topic=source_topic,
                message_id=message_id,
                pubsub_published_at=publish_time,
                firestore_writer=writer,
                replay=replay,
            )
        except ValueError as e:
            log(
                "materialize.bad_event",
                severity="ERROR",
                outcome="failure",
                correlation_id=correlation_id,
                latency_ms=_latency_ms(),
                handler=routed.name,
                messageId=message_id,
                topic=source_topic,
                subscription=subscription,
                error=str(e),
            )
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            log(
                "materialize.exception",
                severity="ERROR",
                outcome="failure",
                correlation_id=correlation_id,
                latency_ms=_latency_ms(),
                handler=routed.name,
                messageId=message_id,
                topic=source_topic,
                subscription=subscription,
                error=str(e),
            )
            raise HTTPException(status_code=500, detail="materialize_exception") from e

        # Post-dedupe observability (best-effort) - no gating.
        try:
            writer.observe_pubsub_delivery(
                message_id=message_id,
                topic=source_topic,
                subscription=subscription,
                handler=routed.name,
                published_at=publish_time,
                delivery_attempt=delivery_attempt,
            )
        except Exception:
            pass

        if replay is not None:
            try:
                write_replay_marker(
                    db=writer._db,  # intentionally internal; minimal hook
                    replay=replay,
                    message_id=message_id,
                    pubsub_published_at=publish_time,
                    event_time=_parse_rfc3339(result.get("eventTime") or result.get("updatedAt")) or publish_time,
                    handler=routed.name,
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
            latency_ms=_latency_ms(),
            handler=routed.name,
            messageId=message_id,
            topic=source_topic,
            subscription=subscription,
            deliveryAttempt=delivery_attempt,
            header_subscription=hdr.get("header_subscription"),
            header_topic=hdr.get("header_topic"),
            applied=result.get("applied"),
            reason=result.get("reason"),
            **{"source.messageId": message_id},
        )
        return {"ok": True, **result}


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.getenv("PORT") or "8080")
    uvicorn.run("cloudrun_consumer.main:app", host="0.0.0.0", port=port, log_level="warning", access_log=False)

