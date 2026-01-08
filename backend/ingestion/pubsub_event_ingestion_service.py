from __future__ import annotations

from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import os
import time
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import Response

import logging

from backend.common.logging import init_structured_logging, install_fastapi_request_id_middleware, log_event
from backend.common.ops_metrics import REGISTRY
from backend.ingestion.pubsub_event_store import build_event_store, parse_pubsub_push
from backend.ingestion.pubsub_push_validation import validate_pubsub_push_headers
from backend.ingestion.ingest_heartbeat_handler import (
    apply_ingest_heartbeat_to_firestore,
    extract_subscription_id,
    parse_ingest_heartbeat,
)
import asyncio

logger = logging.getLogger("pubsub-event-ingestion")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


app = FastAPI(title="Pub/Sub Event Ingestion (Visibility)", version="0.1.0")
init_structured_logging(service="pubsub-event-ingestion")
install_fastapi_request_id_middleware(app, service="pubsub-event-ingestion")
logger = logging.getLogger("pubsub_event_ingestion")


@app.on_event("startup")
async def _startup() -> None:
    # Store is a simple singleton; keeps in-memory mode working across requests.
    app.state.store = build_event_store()
    app.state.ready = True
    app.state.shutting_down = False
    app.state.loop_heartbeat_monotonic = time.monotonic()
    app.state.loop_task = None

    async def _loop_heartbeat() -> None:
        # Tolerate zero producers: liveness should not depend on Pub/Sub traffic.
        while not getattr(app.state, "shutting_down", False):
            app.state.loop_heartbeat_monotonic = time.monotonic()
            await asyncio.sleep(1.0)

    try:
        app.state.loop_task = asyncio.create_task(_loop_heartbeat())
    except Exception:
        app.state.loop_task = None


@app.on_event("shutdown")
async def _shutdown() -> None:
    app.state.shutting_down = True
    app.state.ready = False
    task = getattr(app.state, "loop_task", None)
    if task is not None:
        try:
            task.cancel()
        except Exception:
            pass


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "pubsub-event-ingestion", "ts": _utcnow_iso()}


@app.get("/ops/health")
async def ops_health() -> dict[str, Any]:
    return {"status": "ok", "service": "pubsub-event-ingestion", "ts": _utcnow_iso()}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    ready = bool(getattr(app.state, "ready", False))
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    ok = ready and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "not_ready", "service": "pubsub-event-ingestion"}


@app.get("/livez")
async def livez(response: Response) -> dict[str, Any]:
    now = time.monotonic()
    last = float(getattr(app.state, "loop_heartbeat_monotonic", 0.0) or 0.0)
    max_age_s = float(os.getenv("LIVEZ_MAX_AGE_S") or "30")
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    age_s = max(0.0, now - last)
    ok = (age_s <= max_age_s) and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "wedged", "age_seconds": age_s, "max_age_seconds": max_age_s}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=REGISTRY.render_prometheus_text(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/ops/metrics")
async def ops_metrics() -> Response:
    return await metrics()


@app.post("/pubsub/push")
async def pubsub_push(req: Request) -> dict[str, Any]:
    """
    Pub/Sub push subscription handler.

    This intentionally does NOT do auth hardening yet (visibility-first).
    """
    # Validate Pub/Sub headers (no auth decisions).
    try:
        hdr = validate_pubsub_push_headers(req, subscription_from_body=None)
    except HTTPException as e:
        log_event(
            logger,
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_headers",
            error=str(getattr(e, "detail", "")),
            subscription=None,
            messageId=None,
            publishTime=None,
        )
        raise

    try:
        body = await req.json()
    except Exception as e:
        log_event(
            logger,
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_json",
            error=str(e),
            subscription=hdr.get("header_subscription"),
            messageId=None,
            publishTime=None,
        )
        raise HTTPException(status_code=400, detail="invalid_json") from e

    subscription_raw = body.get("subscription") if isinstance(body, dict) else None
    subscription_s = subscription_raw.strip() if isinstance(subscription_raw, str) else None
    msg = body.get("message") if isinstance(body, dict) else None
    message_id_raw = msg.get("messageId") if isinstance(msg, dict) else None
    publish_time_raw = msg.get("publishTime") if isinstance(msg, dict) else None

    # Validate header/body consistency when possible.
    try:
        hdr = validate_pubsub_push_headers(req, subscription_from_body=subscription_s)
    except HTTPException as e:
        log_event(
            logger,
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_headers",
            error=str(getattr(e, "detail", "")),
            subscription=subscription_s,
            messageId=str(message_id_raw).strip() if isinstance(message_id_raw, str) and message_id_raw.strip() else None,
            publishTime=str(publish_time_raw).strip() if isinstance(publish_time_raw, str) and publish_time_raw.strip() else None,
        )
        raise

    try:
        ev = parse_pubsub_push(body)
    except Exception as e:
        log_event(
            logger,
            "pubsub.rejected",
            severity="ERROR",
            reason="invalid_envelope",
            error=str(e),
            subscription=subscription_s or hdr.get("header_subscription"),
            messageId=str(message_id_raw).strip() if isinstance(message_id_raw, str) and message_id_raw.strip() else None,
            publishTime=str(publish_time_raw).strip() if isinstance(publish_time_raw, str) and publish_time_raw.strip() else None,
        )
        raise HTTPException(status_code=400, detail="invalid_envelope") from e

    log_event(
        logger,
        "pubsub.accepted",
        severity="INFO",
        subscription=ev.subscription,
        messageId=ev.message_id,
        publishTime=(str(publish_time_raw).strip() if isinstance(publish_time_raw, str) else None),
        header_subscription=hdr.get("header_subscription"),
        header_topic=hdr.get("header_topic"),
    )

    # Mark loop heartbeat so /livez shows recent request handling.
    app.state.loop_heartbeat_monotonic = time.monotonic()

    store = app.state.store
    store.write_event(ev)

    # Single-topic end-to-end proof slice:
    # Only apply Firestore business updates when this push comes from the
    # ingest-heartbeat subscription/topic.
    expected_sub_id = (os.getenv("INGEST_HEARTBEAT_SUBSCRIPTION_ID") or "ingest-heartbeat").strip()
    sub_id = extract_subscription_id(ev.subscription)
    if sub_id != expected_sub_id:
        return {"ok": True, "event_id": ev.event_id, "event_type": ev.event_type, "ignored": True}

    hb = parse_ingest_heartbeat(ev)
    if hb is None:
        # Ack malformed/unexpected payloads to avoid infinite redelivery loops.
        return {
            "ok": True,
            "event_id": ev.event_id,
            "event_type": ev.event_type,
            "ingest_heartbeat": {"accepted": False, "reason": "unable_to_parse"},
        }

    try:
        res = apply_ingest_heartbeat_to_firestore(
            hb=hb,
            pubsub_message_id=str(ev.event_id),
            pubsub_publish_time_utc=ev.publish_time_utc,
            project_id=os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None,
        )
        log_event(
            logger,
            "ingest_heartbeat.write",
            severity="INFO",
            pipeline_id=hb.pipeline_id,
            outcome=res.outcome,
            reason=res.reason,
            subscription=ev.subscription,
            message_id=ev.message_id,
            **{"source.messageId": ev.message_id},
        )
        return {
            "ok": True,
            "event_id": ev.event_id,
            "event_type": ev.event_type,
            "ingest_heartbeat": {
                "accepted": True,
                "outcome": res.outcome,
                "pipeline_doc": res.pipeline_doc_path,
                "dedupe_doc": res.dedupe_doc_path,
                "reason": res.reason,
            },
        }
    except Exception as e:
        log_event(
            logger,
            "ingest_heartbeat.write_exception",
            severity="ERROR",
            pipeline_id=hb.pipeline_id,
            error=str(e),
            subscription=ev.subscription,
            message_id=ev.message_id,
            **{"source.messageId": ev.message_id},
        )
        # Correctness: return non-2xx so Pub/Sub retries.
        # Idempotency is guaranteed by the dedupe document keyed by message_id.
        raise HTTPException(
            status_code=500,
            detail={
                "ok": False,
                "event_id": ev.event_id,
                "event_type": ev.event_type,
                "ingest_heartbeat": {"accepted": True, "outcome": "error", "error": str(e)},
            },
        )


@app.get("/api/v1/pubsub/summary")
async def pubsub_summary() -> dict[str, Any]:
    store = app.state.store
    s = store.get_summary()

    last_iso: str | None
    if s.last_event_time_utc is None:
        last_iso = None
    else:
        dt = s.last_event_time_utc
        if getattr(dt, "tzinfo", None) is None:
            dt = dt.replace(tzinfo=timezone.utc)
        last_iso = dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    return {
        "ts": _utcnow_iso(),
        "message_count": int(s.message_count),
        "last_event_time": last_iso,
        "latest_payload_by_event_type": s.latest_payload_by_event_type,
    }

