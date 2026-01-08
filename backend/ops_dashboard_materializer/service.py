from __future__ import annotations

from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response

import asyncio
from backend.common.logging import init_structured_logging, install_fastapi_request_id_middleware, log_event
from backend.ingestion.pubsub_event_store import parse_pubsub_push
from backend.ops_dashboard_materializer.firestore_write_layer import (
    FirestoreWriteLayer,
    SourceInfo,
    log_write_outcome,
)
from backend.ops_dashboard_materializer.models import RouteConfig, schema_version_from, translate_payload_forward, utc_now

logger = logging.getLogger("ops_dashboard_materializer")


SERVICE_NAME = "ops-dashboard-materializer"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_routes_from_env() -> list[RouteConfig]:
    """
    Reads routing config from DASHBOARD_MATERIALIZER_ROUTES_JSON.

    Example:
      [
        {"subscription":"projects/..../subscriptions/ops-services-sub","kind":"ops_services","topic":"ops.status"},
        {"subscription":"projects/..../subscriptions/ops-strategies-sub","kind":"ops_strategies"},
        {"subscription":"projects/..../subscriptions/ingest-pipelines-sub","kind":"ingest_pipelines"},
        {"subscription":"projects/..../subscriptions/ops-alerts-sub","kind":"ops_alerts"}
      ]
    """
    raw = (os.getenv("DASHBOARD_MATERIALIZER_ROUTES_JSON") or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception as e:
        raise RuntimeError("Invalid DASHBOARD_MATERIALIZER_ROUTES_JSON (must be JSON).") from e
    if not isinstance(data, list):
        raise RuntimeError("DASHBOARD_MATERIALIZER_ROUTES_JSON must be a JSON array.")
    routes: list[RouteConfig] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        sub = str(item.get("subscription") or "").strip()
        kind = str(item.get("kind") or "").strip()
        topic = item.get("topic")
        topic_s = str(topic).strip() if isinstance(topic, str) and topic.strip() else None
        if not sub or not kind:
            continue
        routes.append(RouteConfig(subscription=sub, kind=kind, topic=topic_s))  # type: ignore[arg-type]
    return routes


def _find_route(routes: list[RouteConfig], subscription: Optional[str]) -> Optional[RouteConfig]:
    if not subscription:
        return None
    sub = subscription.strip()
    # Exact match preferred.
    for r in routes:
        if r.subscription == sub:
            return r
    # Allow match by short name suffix for convenience.
    short = sub.split("/subscriptions/")[-1]
    for r in routes:
        r_short = r.subscription.split("/subscriptions/")[-1]
        if r_short == short:
            return r
    return None


app = FastAPI(title="Ops Dashboard Materializer", version="0.1.0")
init_structured_logging(service=SERVICE_NAME)
install_fastapi_request_id_middleware(app, service=SERVICE_NAME)


@app.on_event("startup")
async def _startup() -> None:
    project_id = os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None
    app.state.writer = FirestoreWriteLayer(project_id=project_id)
    app.state.routes = _load_routes_from_env()
    app.state.ready = True
    app.state.shutting_down = False
    app.state.loop_heartbeat_monotonic = time.monotonic()
    app.state.loop_task = None
    log_event(logger, "startup", severity="INFO", service=SERVICE_NAME, route_count=len(app.state.routes))

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
    log_event(logger, "shutdown", severity="INFO", service=SERVICE_NAME)
    task = getattr(app.state, "loop_task", None)
    if task is not None:
        try:
            task.cancel()
        except Exception:
            pass


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": SERVICE_NAME, "ts": _utcnow_iso()}


@app.get("/ops/health")
async def ops_health() -> dict[str, Any]:
    return {"status": "ok", "service": SERVICE_NAME, "ts": _utcnow_iso()}


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, Any]:
    ready = bool(getattr(app.state, "ready", False))
    shutting_down = bool(getattr(app.state, "shutting_down", False))
    ok = ready and (not shutting_down)
    response.status_code = 200 if ok else 503
    return {"status": "ok" if ok else "not_ready", "service": SERVICE_NAME}


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


@app.post("/pubsub/push")
async def pubsub_push(req: Request) -> dict[str, Any]:
    """
    Pub/Sub push handler (Cloud Run).

    Processing rules (mandatory):
    - at-least-once safe (idempotent writes)
    - ordering-agnostic (stale update rejection)
    - schema-version aware (translate forward)
    - server-only writes (this service is the only writer)
    """
    try:
        body = await req.json()
    except Exception as e:
        log_event(logger, "pubsub.invalid_json", severity="ERROR", error=str(e))
        raise HTTPException(status_code=400, detail="invalid_json") from e

    try:
        ev = parse_pubsub_push(body)
    except Exception as e:
        log_event(logger, "pubsub.invalid_envelope", severity="ERROR", error=str(e))
        raise HTTPException(status_code=400, detail="invalid_envelope") from e

    # Mark loop heartbeat so /livez shows recent request handling.
    app.state.loop_heartbeat_monotonic = time.monotonic()

    subscription = ev.subscription
    route = _find_route(getattr(app.state, "routes", []) or [], subscription)
    if route is None:
        log_event(
            logger,
            "pubsub.unrouted_subscription",
            severity="ERROR",
            subscription=subscription,
            message_id=ev.message_id,
        )
        # Non-2xx triggers retry and DLQ if configured.
        raise HTTPException(status_code=500, detail="unrouted_subscription")

    payload = ev.payload
    if not isinstance(payload, dict):
        log_event(
            logger,
            "pubsub.payload_not_object",
            severity="ERROR",
            subscription=subscription,
            message_id=ev.message_id,
            event_type=ev.event_type,
        )
        raise HTTPException(status_code=400, detail="payload_not_object")

    schema_version = schema_version_from(payload, ev.attributes)
    writer: FirestoreWriteLayer = app.state.writer
    payload = translate_payload_forward(schema_version=schema_version, payload=payload)

    published_at = ev.publish_time_utc or utc_now()
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    # ---- Route to Firestore projections (NO RAW EVENTS STORED) ----
    try:
        if route.kind == "ops_services":
            if not route.topic:
                log_event(
                    logger,
                    "route.missing_topic",
                    severity="ERROR",
                    subscription=subscription,
                    kind=route.kind,
                )
                raise HTTPException(status_code=500, detail="missing_topic_for_ops_services")

            fields = writer.extract_ops_service_fields(payload)
            service_id = str(fields.get("serviceId") or "").strip()
            if not service_id:
                raise HTTPException(status_code=400, detail="missing_serviceId")

            source = SourceInfo(
                topic=route.topic,
                subscription=str(subscription or ""),
                messageId=str(ev.message_id or ""),
                publishedAt=published_at,
            )
            applied, reason = writer.write_ops_service_latest(
                service_id=service_id,
                status=str(fields.get("status") or ""),
                last_heartbeat_at=fields.get("lastHeartbeatAt"),
                version=str(fields.get("version") or ""),
                region=str(fields.get("region") or ""),
                instance_count=fields.get("instanceCount"),
                source=source,
            )
            log_write_outcome(
                kind=route.kind,
                doc_id=service_id,
                applied=applied,
                reason=reason,
                subscription=subscription,
                message_id=ev.message_id,
            )
            return {"ok": True, "kind": route.kind, "docId": service_id, "schemaVersion": schema_version, "applied": applied}

        if route.kind == "ops_strategies":
            fields = writer.extract_ops_strategy_fields(payload)
            strategy_id = str(fields.get("strategyId") or "").strip()
            if not strategy_id:
                raise HTTPException(status_code=400, detail="missing_strategyId")
            applied, reason = writer.write_ops_strategy_latest(
                strategy_id=strategy_id,
                mode=str(fields.get("mode") or ""),
                status=str(fields.get("status") or ""),
                last_decision_at=fields.get("lastDecisionAt"),
                last_heartbeat_at=fields.get("lastHeartbeatAt"),
                effective_at=fields.get("effectiveAt"),
            )
            log_write_outcome(
                kind=route.kind,
                doc_id=strategy_id,
                applied=applied,
                reason=reason,
                subscription=subscription,
                message_id=ev.message_id,
            )
            return {"ok": True, "kind": route.kind, "docId": strategy_id, "schemaVersion": schema_version, "applied": applied}

        if route.kind == "ingest_pipelines":
            fields = writer.extract_ingest_pipeline_fields(payload)
            pipeline_id = str(fields.get("pipelineId") or "").strip()
            if not pipeline_id:
                raise HTTPException(status_code=400, detail="missing_pipelineId")
            applied, reason = writer.write_ingest_pipeline_latest(
                pipeline_id=pipeline_id,
                status=str(fields.get("status") or ""),
                lag_seconds=fields.get("lagSeconds"),
                throughput_per_min=fields.get("throughputPerMin"),
                error_rate_per_min=fields.get("errorRatePerMin"),
                last_success_at=fields.get("lastSuccessAt"),
                last_error_at=fields.get("lastErrorAt"),
                last_event_at=fields.get("lastEventAt"),
            )
            log_write_outcome(
                kind=route.kind,
                doc_id=pipeline_id,
                applied=applied,
                reason=reason,
                subscription=subscription,
                message_id=ev.message_id,
            )
            return {"ok": True, "kind": route.kind, "docId": pipeline_id, "schemaVersion": schema_version, "applied": applied}

        if route.kind == "ops_alerts":
            fields = writer.extract_ops_alert_fields(payload)
            alert_id = str(fields.get("alertId") or "").strip()
            if not alert_id:
                raise HTTPException(status_code=400, detail="missing_alertId")
            applied, reason = writer.upsert_ops_alert_latest(
                alert_id=alert_id,
                severity=str(fields.get("severity") or "info"),
                state=str(fields.get("state") or "open"),
                entity_ref=fields.get("entityRef"),
                published_at=published_at,
            )
            log_write_outcome(
                kind=route.kind,
                doc_id=alert_id,
                applied=applied,
                reason=reason,
                subscription=subscription,
                message_id=ev.message_id,
            )
            return {"ok": True, "kind": route.kind, "docId": alert_id, "schemaVersion": schema_version, "applied": applied}

        log_event(logger, "route.unknown_kind", severity="ERROR", kind=str(route.kind), subscription=subscription)
        raise HTTPException(status_code=500, detail="unknown_kind")

    except HTTPException:
        # Non-2xx -> Pub/Sub retry + DLQ compatibility.
        raise
    except Exception as e:
        log_event(
            logger,
            "materializer.exception",
            severity="ERROR",
            error=str(e),
            subscription=subscription,
            message_id=ev.message_id,
            kind=route.kind,
            schemaVersion=schema_version,
            payload_type=str(type(payload).__name__),
        )
        raise HTTPException(status_code=500, detail="materializer_exception") from e

