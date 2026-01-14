from __future__ import annotations

from backend.common.agent_mode_guard import enforce_agent_mode_guard as _enforce_agent_mode_guard

_enforce_agent_mode_guard()

import json
import logging
import os
import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.common.agent_state_machine import (
    AgentState,
    AgentStateMachine,
    read_agent_mode,
    trading_allowed,
)
from backend.common.agent_mode import AgentModeError
from backend.common.agent_boot import configure_startup_logging
from backend.common.replay_events import build_replay_event, dumps_replay_event, set_replay_context
from backend.common.logging import init_structured_logging, install_fastapi_request_id_middleware
from backend.execution.engine import (
    AlpacaBroker,
    DryRunBroker,
    ExecutionEngine,
    ExecutionResult,
    OrderIntent,
    RiskManager,
)
from backend.persistence.idempotency_store import FirestoreIdempotencyStore
from backend.common.agent_mode_guard import enforce_agent_mode_guard
from backend.common.kill_switch import get_kill_switch_state
from backend.common.agent_boot import configure_startup_logging
from backend.common.app_heartbeat_writer import install_app_heartbeat
from backend.common.vertex_ai import init_vertex_ai_or_log
from backend.execution.marketdata_health import check_market_ingest_heartbeat
from backend.observability.build_fingerprint import get_build_fingerprint
from backend.observability.execution_id import bind_execution_id
from backend.ops.status_contract import AgentIdentity, EndpointsBlock, build_ops_status
from backend.persistence.firebase_client import get_firestore_client
from backend.persistence.firestore_retry import with_firestore_retry
from backend.risk.daily_capital_snapshot import DailyCapitalSnapshotError, DailyCapitalSnapshotStore
from backend.time.nyse_time import to_nyse
from backend.safety.startup_validation import (
    validate_agent_mode_or_exit,
    validate_flag_exact_false_or_exit,
    validate_required_env_or_exit,
)
from backend.observability.ops_json_logger import OpsLogger
from backend.common.ops_metrics import REGISTRY
from backend.execution.order_recovery import (
    FirestoreExecutionOrderStore,
    TimeoutRules,
    infer_asset_class,
    is_open_status,
    is_terminal_status,
    is_stale_for_poll,
    is_unfilled_past_timeout,
    timeout_seconds_for_intent,
 )

init_structured_logging(service="execution-engine")

logger = logging.getLogger(__name__)


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


class ExecuteIntentRequest(BaseModel):
    strategy_id: str = Field(..., description="Strategy identifier")
    broker_account_id: str = Field(..., description="Broker account id (e.g. paper/live account)")
    symbol: str = Field(..., description="Ticker symbol, e.g. SPY")
    side: str = Field(..., description="buy|sell")
    qty: float = Field(..., gt=0, description="Order quantity")

    order_type: str = Field(default="market", description="market|limit|...")
    time_in_force: str = Field(default="day", description="day|gtc|...")
    limit_price: Optional[float] = Field(default=None, description="Required for limit orders")

    client_intent_id: Optional[str] = Field(
        default=None, description="Optional idempotency/audit identifier"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecuteIntentResponse(BaseModel):
    status: str
    risk: dict[str, Any]
    broker_order_id: Optional[str] = None
    broker_order: Optional[dict[str, Any]] = None
    message: Optional[str] = None


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    return int(v)


def _build_engine_from_env() -> tuple[ExecutionEngine, RiskManager]:
    """
    Constructs the engine from env vars.

    ADC / Firestore:
    - Uses `backend.persistence.firebase_client` which initializes Firebase Admin SDK via ADC.
    - On Cloud Run, attach a service account with Firestore permissions.
    """
    dry_run = _bool_env("EXEC_DRY_RUN", True)
    risk = RiskManager()
    broker = DryRunBroker() if dry_run else AlpacaBroker()
    return (ExecutionEngine(broker=broker, broker_name="alpaca", dry_run=dry_run, risk=risk), risk)


def _resolve_idempotency_key(req: ExecuteIntentRequest) -> str:
    """
    Resolve a replay-stable idempotency key for execution.

    Preference order:
    - correlation_id (preferred for "single-use per correlation_id" safety)
    - explicit request field: client_intent_id
    - metadata-derived keys commonly present in event envelopes
    - NO fallback: callers must provide a stable key to be replay-safe
    """
    candidates = [
        (req.metadata or {}).get("correlation_id"),
        req.client_intent_id,
        (req.metadata or {}).get("idempotency_key"),
        (req.metadata or {}).get("client_intent_id"),
        (req.metadata or {}).get("intent_id"),
        # Common correlation ids in this repo's trade pipeline.
        (req.metadata or {}).get("execution_id"),
        (req.metadata or {}).get("signal_id"),
        (req.metadata or {}).get("allocation_id"),
        (req.metadata or {}).get("event_id"),
        (req.metadata or {}).get("message_id"),
        (req.metadata or {}).get("trace_id"),
        (req.metadata or {}).get("run_id"),
    ]
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if s:
            return s

    raise ValueError(
        "missing_idempotency_key: provide client_intent_id or metadata.correlation_id (or another stable metadata key)"
    )


app = FastAPI(title="AgentTrader Execution Engine")
install_fastapi_request_id_middleware(app, service="execution-engine")
install_app_heartbeat(app, service_name="execution-engine")


def _require_admin(request: Request) -> None:
    required = str(os.getenv("EXEC_AGENT_ADMIN_KEY") or "").strip()
    if not required:
        # Hide internal endpoints unless explicitly enabled.
        raise HTTPException(status_code=404, detail="not_found")
    provided = str(request.headers.get("X-Exec-Agent-Key") or "").strip()
    if provided != required:
        raise HTTPException(status_code=401, detail="unauthorized")


def _resolve_tenant_id_from_request_metadata(md: dict[str, Any]) -> str | None:
    return str(md.get("tenant_id") or os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID") or "").strip() or None


def _resolve_uid_from_request_metadata(md: dict[str, Any]) -> str | None:
    return str(md.get("uid") or md.get("user_id") or os.getenv("EXEC_UID") or "").strip() or None


def _intent_snapshot(intent: OrderIntent) -> dict[str, Any]:
    # Keep this strict + JSON-safe (for replay + recovery).
    return {
        "strategy_id": intent.strategy_id,
        "broker_account_id": intent.broker_account_id,
        "symbol": intent.symbol,
        "side": intent.side,
        "qty": float(intent.qty),
        "order_type": intent.order_type,
        "time_in_force": intent.time_in_force,
        "limit_price": float(intent.limit_price) if intent.limit_price is not None else None,
        "asset_class": intent.asset_class,
        "client_intent_id": intent.client_intent_id,
        "created_at_utc": intent.created_at.astimezone(timezone.utc).isoformat(),
        # Minimal metadata needed for safe reconciliation
        "metadata": {
            "tenant_id": str((intent.metadata or {}).get("tenant_id") or "").strip() or None,
            "uid": str((intent.metadata or {}).get("uid") or (intent.metadata or {}).get("user_id") or "").strip() or None,
            "correlation_id": str((intent.metadata or {}).get("correlation_id") or "").strip() or None,
            "trace_id": str((intent.metadata or {}).get("trace_id") or "").strip() or None,
            "run_id": str((intent.metadata or {}).get("run_id") or "").strip() or None,
        },
    }


def _intent_from_snapshot(snap: dict[str, Any]) -> OrderIntent:
    md = dict((snap or {}).get("metadata") or {})
    return OrderIntent(
        strategy_id=str(snap.get("strategy_id") or ""),
        broker_account_id=str(snap.get("broker_account_id") or ""),
        symbol=str(snap.get("symbol") or ""),
        side=str(snap.get("side") or ""),
        qty=float(snap.get("qty") or 0.0),
        order_type=str(snap.get("order_type") or "market"),
        time_in_force=str(snap.get("time_in_force") or "day"),
        limit_price=float(snap.get("limit_price")) if snap.get("limit_price") is not None else None,
        asset_class=str(snap.get("asset_class") or infer_asset_class(metadata=md)).strip().upper(),
        client_intent_id=str(snap.get("client_intent_id") or ""),
        created_at=datetime.now(timezone.utc),
        metadata={k: v for k, v in md.items() if v is not None},
    ).normalized()


@app.on_event("startup")
def _startup() -> None:
    enforce_agent_mode_guard()
    configure_startup_logging(
        agent_name="execution-engine",
        intent="Serve the execution API; validate config and execute broker order intents.",
    )
    app.state.ops_logger = OpsLogger("execution-engine")
    try:
        fp = get_build_fingerprint()
        logger.info(
            "build_fingerprint",
            extra={
                "event_type": "build_fingerprint",
                "intent_type": "build_fingerprint",
                "service": "execution-engine",
                **fp,
            },
        )
    except Exception:
        pass
    # Best-effort: validate Vertex AI model config without crashing the service.
    try:
        init_vertex_ai_or_log()
    except Exception as e:  # pragma: no cover
        logger.warning("Vertex AI validation skipped (non-fatal): %s", e)

    # Initialize long-lived agent components once (instead of per-request):
    # - execution engine (broker clients can keep connection pools)
    # - risk manager (kill-switch checks)
    # - explicit agent state machine
    engine, risk = _build_engine_from_env()
    app.state.engine = engine
    app.state.risk = risk
    app.state.agent_sm = AgentStateMachine(agent_id=str(os.getenv("EXEC_AGENT_ID") or "execution_engine"))
    app.state.order_store = FirestoreExecutionOrderStore(
        project_id=os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None
    )
    app.state.shutting_down = False
    # If kill-switch is active at boot, make it visible immediately.
    try:
        enabled, source = get_kill_switch_state()
        if enabled:
            logger.warning("kill_switch_active enabled=true source=%s", source)
    except Exception:
        pass
    try:
        app.state.ops_logger.readiness(ready=True)  # type: ignore[attr-defined]
    except Exception:
        pass

@app.on_event("shutdown")
async def _shutdown() -> None:
    # Prevent new /execute calls and refuse starting new broker submissions.
    try:
        app.state.shutting_down = True
    except Exception:
        pass
    try:
        _request_shutdown(reason="fastapi_shutdown")
    except Exception:
        pass
    try:
        app.state.ops_logger.shutdown(phase="initiated")  # type: ignore[attr-defined]
    except Exception:
        pass
    # Best-effort: wait briefly for any in-flight broker submissions to finish.
    try:
        timeout_s = float(os.getenv("EXEC_SHUTDOWN_DRAIN_TIMEOUT_S") or "8")
        drained = await asyncio.to_thread(_wait_for_inflight_zero, timeout_s=timeout_s)
        if not drained:
            logger.warning("exec_service.shutdown_drain_timeout timeout_s=%s", timeout_s)
    except Exception:
        pass


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "execution-engine", **get_build_fingerprint()}


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    # Alias for institutional conventions.
    return health()

@app.get("/ops/health")
def ops_health() -> dict[str, Any]:
    return {"status": "ok", "service": "execution-engine", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    # Readiness is equivalent to health for this API (no external calls).
    return {"status": "ok"}

@app.get("/ops/status")
def ops_status() -> dict[str, Any]:
    kill, _source = get_kill_switch_state()
    tenant_id = str(os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID") or "").strip() or None
    stale_s = _int_env("MARKETDATA_STALE_THRESHOLD_S", 120)
    hb = check_market_ingest_heartbeat(tenant_id=tenant_id, stale_threshold_seconds=stale_s)

    # Execution can be intentionally disabled / scaled to 0.
    execution_enabled = _bool_env("EXECUTION_ENABLED", True)
    execution_replicas = None
    try:
        execution_replicas = int(os.getenv("EXECUTION_REPLICAS") or "") if os.getenv("EXECUTION_REPLICAS") else None
    except Exception:
        execution_replicas = None

    st = build_ops_status(
        service_name="execution-agent",
        service_kind="execution",
        agent_identity=AgentIdentity(
            agent_name=str(os.getenv("AGENT_NAME") or "execution-agent"),
            agent_role=str(os.getenv("AGENT_ROLE") or "execution"),
            agent_mode=str(os.getenv("AGENT_MODE") or read_agent_mode()),
        ),
        git_sha=os.getenv("GIT_SHA") or os.getenv("K_REVISION") or None,
        build_id=os.getenv("BUILD_ID") or None,
        kill_switch=bool(kill),
        heartbeat_ttl_seconds=_int_env("OPS_HEARTBEAT_TTL_S", 60),
        marketdata_last_tick_utc=hb.last_heartbeat_at,
        marketdata_stale_threshold_seconds=stale_s,
        execution_enabled=bool(execution_enabled),
        execution_replicas=execution_replicas,
        endpoints=EndpointsBlock(healthz="/health", heartbeat=None, metrics=None),
    )
    return st.model_dump()


@app.get("/metrics")
def metrics() -> Response:
    return Response(
        content=REGISTRY.render_prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.get("/ops/metrics")
def ops_metrics() -> Response:
    return metrics()


@app.get("/state")
def state(request: Request) -> dict[str, Any]:
    """
    Inspect execution-agent state machine and gating inputs.

    Security/contract rule:
    - This endpoint exposes INTERNAL state intended only for on-call debugging.
    - Other agents/services MUST NOT depend on it.
    - It is disabled unless `EXEC_AGENT_ADMIN_KEY` is explicitly configured.
    """
    _require_admin(request)

    sm: AgentStateMachine = app.state.agent_sm
    risk: RiskManager = app.state.risk

    tenant_id = str(os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID") or "").strip() or None
    stale_s = _int_env("MARKETDATA_STALE_THRESHOLD_S", 120)
    hb = check_market_ingest_heartbeat(tenant_id=tenant_id, stale_threshold_seconds=stale_s)
    kill_enabled, kill_source = get_kill_switch_state()
    kill = bool(kill_enabled)

    # Update state based on latest signals (no-op if unchanged).
    sm.on_kill_switch(enabled=kill, meta={"source": "state_endpoint"})
    if not kill:
        sm.on_marketdata(
            is_stale=hb.is_stale,
            meta={
                "source": "state_endpoint",
                "heartbeat_path": hb.path,
                "heartbeat_age_seconds": hb.age_seconds,
                "heartbeat_status": hb.status,
            },
        )

    agent_mode = read_agent_mode()
    allowed, reason = trading_allowed(state=sm.state, agent_mode=agent_mode, kill_switch_enabled=kill)
    return {
        "agent_id": sm.agent_id,
        "state": sm.state.value,
        "last_transition_at": sm.last_transition_at.isoformat(),
        "error_count": sm.error_count,
        "restart_not_before": sm.restart_not_before.isoformat() if sm.restart_not_before else None,
        "last_error": sm.last_error,
        "agent_mode": agent_mode,
        "engine_dry_run": bool(getattr(app.state.engine, "dry_run", True)),
        "kill_switch_enabled": kill,
        "kill_switch_source": kill_source,
        "marketdata_heartbeat": {
            "path": hb.path,
            "exists": hb.exists,
            "last_heartbeat_at": hb.last_heartbeat_at.isoformat() if hb.last_heartbeat_at else None,
            "age_seconds": hb.age_seconds,
            "is_stale": hb.is_stale,
            "status": hb.status,
            "stale_threshold_seconds": stale_s,
        },
        "live_trading_allowed": allowed,
        "live_trading_block_reason": reason,
    }


@app.post("/recover")
def recover(request: Request) -> dict[str, Any]:
    """
    Manual "recover => READY" transition.

    If EXEC_AGENT_ADMIN_KEY is set, callers must provide matching header:
      X-Exec-Agent-Key: <key>
    """
    _require_admin(request)

    sm: AgentStateMachine = app.state.agent_sm
    sm.recover(reason="manual_recover", meta={"source": "recover_endpoint"})
    return {"status": "ok", "state": sm.state.value}


@app.post("/execute", response_model=ExecuteIntentResponse)
def execute(req: ExecuteIntentRequest, request: Request) -> ExecuteIntentResponse:
    if bool(getattr(app.state, "shutting_down", False)):
        # Graceful shutdown contract: refuse new executions (prevents partial submissions).
        raise HTTPException(status_code=503, detail="shutting_down")
    engine: ExecutionEngine = app.state.engine
    risk: RiskManager = app.state.risk
    sm: AgentStateMachine = app.state.agent_sm
    # Prefer caller-provided trace_id; fall back to client_intent_id.
    trace_id = str(req.metadata.get("trace_id") or req.client_intent_id or "").strip() or None
    if trace_id:
        set_replay_context(trace_id=trace_id)
    try:
        idempotency_key = _resolve_idempotency_key(req)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "missing_idempotency_key",
                "message": str(e),
                "required": "Provide client_intent_id or metadata.correlation_id (recommended) for replay-safe execution.",
            },
        ) from e
    intent = OrderIntent(
        strategy_id=req.strategy_id,
        broker_account_id=req.broker_account_id,
        symbol=req.symbol,
        side=req.side,
        qty=req.qty,
        order_type=req.order_type,
        time_in_force=req.time_in_force,
        limit_price=req.limit_price,
        client_intent_id=idempotency_key,
        asset_class=infer_asset_class(metadata=req.metadata),
        metadata=req.metadata,
    )

    # --- Daily capital snapshot guard (no trade before/after window; no date drift) ---
    try:
        tenant_for_snapshot = str(
            req.metadata.get("tenant_id")
            or os.getenv("TENANT_ID")
            or os.getenv("EXEC_TENANT_ID")
            or ""
        ).strip()
        uid_for_snapshot = str(req.metadata.get("uid") or req.metadata.get("user_id") or "").strip()
        if not tenant_for_snapshot or not uid_for_snapshot:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "missing_tenant_or_uid",
                    "message": "Execution requires metadata.tenant_id and metadata.uid (or metadata.user_id) to enforce DailyCapitalSnapshot.",
                },
            )
        db = get_firestore_client()
        acct_doc = with_firestore_retry(
            lambda: db.collection("users")
            .document(uid_for_snapshot)
            .collection("alpacaAccounts")
            .document("snapshot")
            .get()
        )
        if not acct_doc.exists:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "missing_account_snapshot",
                    "message": f"Missing warm-cache account snapshot at users/{uid_for_snapshot}/alpacaAccounts/snapshot",
                },
            )
        acct = acct_doc.to_dict() or {}
        now = datetime.now(timezone.utc)
        trading_date_ny = to_nyse(now).date()
        store = DailyCapitalSnapshotStore(db=db)
        snap = store.get_or_create_once(
            tenant_id=tenant_for_snapshot,
            uid=uid_for_snapshot,
            trading_date_ny=trading_date_ny,
            account_snapshot=acct,
            now_utc=now,
            source="execution_service.execute",
        )
        snap.assert_date_match(trading_date_ny=trading_date_ny)
        snap.assert_trade_window(now_utc=now)
    except DailyCapitalSnapshotError as e:
        msg = str(e)
        if "fingerprint mismatch" in msg or "Trading day mismatch" in msg:
            raise HTTPException(status_code=500, detail={"error": "daily_capital_snapshot_invalid", "message": msg})
        raise HTTPException(status_code=409, detail={"error": "daily_capital_snapshot_blocked", "message": msg})

    # --- Update state machine inputs for this request ---
    agent_mode = read_agent_mode()
    tenant_id = str(req.metadata.get("tenant_id") or os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID") or "").strip() or None
    stale_s = _int_env("MARKETDATA_STALE_THRESHOLD_S", 120)
    hb = check_market_ingest_heartbeat(tenant_id=tenant_id, stale_threshold_seconds=stale_s)
    kill_enabled, kill_source = get_kill_switch_state()
    kill = bool(kill_enabled)

    sm.on_kill_switch(enabled=kill, meta={"source": "execute_endpoint"})
    if not kill:
        sm.on_marketdata(
            is_stale=hb.is_stale,
            meta={
                "source": "execute_endpoint",
                "heartbeat_path": hb.path,
                "heartbeat_age_seconds": hb.age_seconds,
                "heartbeat_status": hb.status,
            },
        )

    # If ERROR state has backoff active, refuse quickly with Retry-After semantics.
    if sm.state == AgentState.ERROR and sm.in_backoff():
        retry_after = None
        if sm.restart_not_before:
            now = datetime.now(timezone.utc)
            retry_after = max(0, int((sm.restart_not_before - now).total_seconds()))
        logger.warning(
            "exec_agent.refuse_in_backoff %s",
            json.dumps(
                {
                    "agent_id": sm.agent_id,
                    "state": sm.state.value,
                    "restart_not_before": sm.restart_not_before.isoformat() if sm.restart_not_before else None,
                    "last_error": sm.last_error,
                    "retry_after_s": retry_after,
                }
            ),
        )
        raise HTTPException(status_code=503, detail="agent_in_backoff")

    # Enforce the "refuse live trading unless READY + LIVE + kill-switch off" policy.
    # Note: dry-run execution (no broker routing) is allowed even when not LIVE.
    if not engine.dry_run:
        # --- Per-strategy circuit breaker: consecutive losses (operator-configured, default disabled) ---
        max_consec = _int_env("EXEC_CB_MAX_CONSECUTIVE_LOSSES", 0)
        if max_consec > 0 and tenant_id:
            uid = str(req.metadata.get("uid") or os.getenv("EXEC_UID") or "").strip() or None
            if uid:
                try:
                    from backend.persistence.firebase_client import get_firestore_client  # noqa: WPS433

                    db = get_firestore_client()
                    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                    q = (
                        db.collection("tenants")
                        .document(str(tenant_id))
                        .collection("ledger_trades")
                        .where("uid", "==", str(uid))
                        .where("strategy_id", "==", str(req.strategy_id))
                        .where("ts", ">=", today_start)
                    )
                    trades: list[dict[str, Any]] = []
                    for doc in q.stream():
                        d = doc.to_dict() or {}
                        d["trade_id"] = doc.id
                        trades.append(d)
                    cb = check_consecutive_losses_from_ledger_trades(trades=trades, max_consecutive_losses=max_consec)
                    if cb.triggered:
                        logger.warning(
                            "exec_service.circuit_breaker_triggered %s",
                            json.dumps(
                                {
                                    "breaker_type": "consecutive_losses",
                                    "reason_code": cb.reason_code,
                                    "strategy_id": req.strategy_id,
                                    "tenant_id": tenant_id,
                                    "uid": uid,
                                    "details": cb.details,
                                }
                            ),
                        )
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "refused": True,
                                "reason": "circuit_breaker_consecutive_losses",
                                "breaker": {
                                    "type": "consecutive_losses",
                                    "reason_code": cb.reason_code,
                                    "message": cb.message,
                                    "details": cb.details,
                                },
                            },
                        )
                except HTTPException:
                    raise
                except Exception as e:
                    # Safety posture here is best-effort: do not crash request path due to breaker telemetry.
                    logger.exception("exec_service.circuit_breaker_eval_failed: %s", e)

        allowed, reason = trading_allowed(state=sm.state, agent_mode=agent_mode, kill_switch_enabled=kill)
        if not allowed:
            logger.warning(
                "exec_agent.trade_refused %s",
                json.dumps(
                    {
                        "agent_id": sm.agent_id,
                        "state": sm.state.value,
                        "agent_mode": agent_mode,
                        "kill_switch_enabled": kill,
                        "kill_switch_source": kill_source,
                        "reason": reason,
                        "marketdata_is_stale": hb.is_stale,
                        "marketdata_age_seconds": hb.age_seconds,
                    }
                ),
            )
            raise HTTPException(status_code=409, detail={"refused": True, "reason": reason, "state": sm.state.value})

    # ---- Idempotency guard (prevents duplicate broker orders on replay) ----
    tenant_id_for_idem = (
        str(req.metadata.get("tenant_id") or os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID") or "").strip()
        if isinstance(req.metadata, dict)
        else str(os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID") or "").strip()
    ) or "default"
    idem = FirestoreIdempotencyStore(project_id=os.getenv("FIREBASE_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or None)

    # Additional contract: if an explicit execution_id is provided, refuse duplicates for the same trading day.
    # This is a minimal downstream safety check: it prevents double-execution even if callers accidentally
    # retry with a different client_intent_id.
    execution_id = None
    try:
        execution_id = str((req.metadata or {}).get("execution_id") or "").strip() or None
    except Exception:
        execution_id = None
    if execution_id:
        trading_date_ny = to_nyse(datetime.now(timezone.utc)).date().isoformat()
        acquired_daily, _daily_rec = idem.begin(
            tenant_id=tenant_id_for_idem,
            scope="execution.execution_id_applied_daily",
            key=f"{execution_id}:{trading_date_ny}",
            payload={"execution_id": execution_id, "trading_date_ny": trading_date_ny},
        )
        if not acquired_daily:
            return ExecuteIntentResponse(
                status="duplicate_execution_id",
                risk={"allowed": False, "reason": "execution_id_already_applied_today", "checks": []},
                broker_order_id=None,
                broker_order=None,
                message="execution_id_already_applied_today",
            )

    acquired, record = idem.begin(
        tenant_id=tenant_id_for_idem,
        scope="execution.execute_intent",
        key=idempotency_key,
        payload={
            "strategy_id": req.strategy_id,
            "broker_account_id": req.broker_account_id,
            "symbol": req.symbol,
            "side": req.side,
            "qty": req.qty,
        },
    )
    if not acquired:
        if record.outcome:
            # Replay-safe: return the original outcome without performing side effects.
            return ExecuteIntentResponse(**record.outcome)
        # Conservatively refuse to execute again: prevents duplicate orders even if a prior attempt crashed.
        return ExecuteIntentResponse(
            status="duplicate_in_progress",
            risk={"allowed": False, "reason": "duplicate_in_progress", "checks": []},
            broker_order_id=None,
            broker_order=None,
            message="duplicate_in_progress",
        )
        if not acquired:
            if record.outcome:
                # Replay-safe: return the original outcome without performing side effects.
                return ExecuteIntentResponse(**record.outcome)
            # Conservatively refuse to execute again: prevents duplicate orders even if a prior attempt crashed.
            return ExecuteIntentResponse(
                status="duplicate_in_progress",
                risk={"allowed": False, "reason": "duplicate_in_progress", "checks": []},
                broker_order_id=None,
                broker_order=None,
                message="duplicate_in_progress",
            )

        try:
            result: ExecutionResult = engine.execute_intent(intent=intent)
        except AgentModeError as e:
            logger.warning("exec_service.trading_refused: %s", e)
            try:
                idem.complete(
                    tenant_id=tenant_id_for_idem,
                    scope="execution.execute_intent",
                    key=idempotency_key,
                    status="failed",
                    outcome={
                        "status": "failed",
                        "risk": {"allowed": False, "reason": "trading_refused", "checks": []},
                        "message": str(e),
                    },
                )
            except Exception:
                pass
            raise HTTPException(status_code=409, detail={"error": "trading_refused", "reason": str(e)}) from e
        except Exception as e:
            logger.exception("exec_service.execute_failed: %s", e)
            try:
                logger.error(
                    "%s",
                    dumps_replay_event(
                        build_replay_event(
                            event="state_transition",
                            component="backend.services.execution_service.app",
                            data={
                                "from_state": "intent_received",
                                "to_state": "execute_failed",
                                "strategy_id": req.strategy_id,
                                "symbol": req.symbol,
                                "client_intent_id": req.client_intent_id,
                                "error": str(e),
                            },
                            trace_id=trace_id,
                            agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                        )
                    ),
                )
            except Exception:
                pass
            try:
                idem.complete(
                    tenant_id=tenant_id_for_idem,
                    scope="execution.execute_intent",
                    key=idempotency_key,
                    status="failed",
                    outcome={
                        "status": "failed",
                        "risk": {"allowed": False, "reason": "execution_failed", "checks": []},
                        "message": "execution_failed",
                    },
                )
            except Exception:
                pass
            raise HTTPException(status_code=500, detail="execution_failed") from e

        # Always log an audit event (safe JSON; broker_order may contain ids, not secrets).
        try:
            logger.info(
                "exec_service.execute_result %s",
                json.dumps(
                    {
                        "status": result.status,
                        "risk": {
                            "allowed": result.risk.allowed,
                            "reason": result.risk.reason,
                            "checks": result.risk.checks,
                        },
                        "broker_order_id": result.broker_order_id,
                    }
                ),
            )
        except Exception:
            pass

        resp = ExecuteIntentResponse(
            status=result.status,
            risk={
                "allowed": result.risk.allowed,
                "reason": result.risk.reason,
                "checks": result.risk.checks,
            },
            broker_order_id=result.broker_order_id,
            broker_order=result.broker_order,
            message=result.message,
        )

    # Persist open-order tracking for recovery (best-effort).
    # This is critical for OPTIONS: downstream can reconcile late rejections/timeouts instead of poisoning state.
    try:
        store: FirestoreExecutionOrderStore = app.state.order_store
        tenant_id_for_record = _resolve_tenant_id_from_request_metadata(req.metadata) or tenant_for_snapshot
        uid_for_record = _resolve_uid_from_request_metadata(req.metadata) or uid_for_snapshot
        if tenant_id_for_record and uid_for_record and result.broker_order_id:
            now = datetime.now(timezone.utc)
            broker_status = str((result.broker_order or {}).get("status") or "").strip() or None
            status_for_record = broker_status or str(result.status or "").strip()
            store.upsert(
                tenant_id=tenant_id_for_record,
                client_intent_id=intent.client_intent_id,
                payload={
                    "tenant_id": tenant_id_for_record,
                    "uid": uid_for_record,
                    "client_intent_id": intent.client_intent_id,
                    "broker_order_id": str(result.broker_order_id),
                    "broker_account_id": intent.broker_account_id,
                    "strategy_id": intent.strategy_id,
                    "asset_class": intent.asset_class,
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "qty": float(intent.qty),
                    "order_type": intent.order_type,
                    "time_in_force": intent.time_in_force,
                    "limit_price": float(intent.limit_price) if intent.limit_price is not None else None,
                    "created_at": now,
                    "created_at_iso": now.isoformat(),
                    "status": status_for_record,
                    "status_norm": str(status_for_record or "").strip().lower(),
                    "last_broker_sync_at": now,
                    "last_broker_sync_at_iso": now.isoformat(),
                    "intent_snapshot": _intent_snapshot(intent),
                    "last_broker_order": result.broker_order or None,
                },
            )
    except Exception:
        pass

        # Reject intents via HTTP 409 for easy callers.
        if result.status == "rejected":
            try:
                idem.complete(
                    tenant_id=tenant_id_for_idem,
                    scope="execution.execute_intent",
                    key=idempotency_key,
                    outcome=resp.model_dump(),
                    status="completed",
                )
            except Exception:
                pass
            raise HTTPException(status_code=409, detail=resp.model_dump())

        try:
            idem.complete(
                tenant_id=tenant_id_for_idem,
                scope="execution.execute_intent",
                key=idempotency_key,
                outcome=resp.model_dump(),
                status="completed",
            )
        except Exception:
            pass
        return resp


class RecoverOrdersRequest(BaseModel):
    tenant_id: str | None = None
    asset_class: str = "OPTIONS"
    limit: int = 50
    dry_run: bool = False


@app.post("/orders/recover")
def recover_orders(body: RecoverOrdersRequest, request: Request) -> dict[str, Any]:
    """
    Detect and recover failed/stuck orders.

    - Detect: rejected / stale / unfilled-beyond-timeout
    - Cancel + reconcile: poll broker, write fills if any, cancel timed-out opens, mark terminal, and best-effort release.

    Security:
      - Disabled unless EXEC_AGENT_ADMIN_KEY is configured.
      - Requires header: X-Exec-Agent-Key
    """
    _require_admin(request)
    engine: ExecutionEngine = app.state.engine
    store: FirestoreExecutionOrderStore = app.state.order_store
    rules = TimeoutRules.from_env()

    tenant_id = (str(body.tenant_id).strip() if body.tenant_id else None) or str(
        os.getenv("TENANT_ID") or os.getenv("EXEC_TENANT_ID") or ""
    ).strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail={"error": "missing_tenant_id"})

    asset_class = str(body.asset_class or "").strip().upper() or None
    limit = int(max(1, min(500, body.limit)))
    now = datetime.now(timezone.utc)

    candidates = store.list_open(tenant_id=tenant_id, asset_class=asset_class, limit=limit)
    results: list[dict[str, Any]] = []

    for rec in candidates:
        broker_order_id = rec.broker_order_id
        if not broker_order_id:
            # Nothing actionable; mark as stale record.
            results.append(
                {
                    "client_intent_id": rec.client_intent_id,
                    "action": "noop_missing_broker_order_id",
                }
            )
            continue

        intent = None
        try:
            if rec.intent_snapshot:
                intent = _intent_from_snapshot(rec.intent_snapshot)
        except Exception:
            intent = None

        # Decide whether we need to poll/cancel.
        timeout_s = timeout_seconds_for_intent(
            asset_class=(intent.asset_class if intent else rec.asset_class),
            order_type=(intent.order_type if intent else "market"),
            rules=rules,
        )
        should_poll = is_stale_for_poll(now=now, last_broker_sync_at=rec.last_broker_sync_at, rules=rules)
        should_timeout_cancel = bool(is_unfilled_past_timeout(now=now, created_at=rec.created_at, timeout_s=timeout_s))

        action = "noop"
        broker_order: dict[str, Any] | None = None
        try:
            if should_poll:
                broker_order = engine.sync_and_ledger_if_filled(broker_order_id=broker_order_id, intent=intent)
        except Exception as e:
            results.append(
                {
                    "client_intent_id": rec.client_intent_id,
                    "broker_order_id": broker_order_id,
                    "action": "poll_failed",
                    "error": f"{type(e).__name__}: {e}",
                }
            )
            continue

        # If we polled, use broker status; else fall back to stored status.
        status = str((broker_order or {}).get("status") or rec.status or "").strip()
        status_norm = status.lower()

        # Cancel timed-out open orders.
        if should_timeout_cancel and is_open_status(status_norm):
            if body.dry_run:
                action = "dry_run_timeout_cancel"
            else:
                try:
                    engine.cancel(broker_order_id=broker_order_id)
                    action = "timeout_cancel"
                    # Re-poll once to capture terminal status if possible.
                    try:
                        broker_order = engine.sync_and_ledger_if_filled(broker_order_id=broker_order_id, intent=intent)
                        status = str((broker_order or {}).get("status") or status).strip()
                        status_norm = status.lower()
                    except Exception:
                        pass
                except Exception as e:
                    results.append(
                        {
                            "client_intent_id": rec.client_intent_id,
                            "broker_order_id": broker_order_id,
                            "action": "cancel_failed",
                            "error": f"{type(e).__name__}: {e}",
                        }
                    )
                    continue
        elif should_poll:
            action = "polled"

        # Persist updated state.
        try:
            store.upsert(
                tenant_id=tenant_id,
                client_intent_id=rec.client_intent_id,
                payload={
                    "tenant_id": tenant_id,
                    "client_intent_id": rec.client_intent_id,
                    "broker_order_id": broker_order_id,
                    "asset_class": (intent.asset_class if intent else rec.asset_class),
                    "status": status,
                    "status_norm": status_norm,
                    "last_broker_sync_at": now,
                    "last_broker_sync_at_iso": now.isoformat(),
                    "timeout_s": timeout_s,
                    "timeout_at_iso": (rec.created_at + timedelta(seconds=timeout_s)).isoformat()
                    if rec.created_at
                    else None,
                    "intent_snapshot": rec.intent_snapshot or (_intent_snapshot(intent) if intent else {}),
                    "last_broker_order": broker_order or None,
                },
            )
        except Exception:
            pass

        results.append(
            {
                "client_intent_id": rec.client_intent_id,
                "broker_order_id": broker_order_id,
                "status": status,
                "action": action,
                "timed_out": bool(should_timeout_cancel),
                "stale_polled": bool(should_poll),
                "is_terminal": bool(is_terminal_status(status_norm)),
            }
        )

    return {
        "tenant_id": tenant_id,
        "asset_class": asset_class,
        "rules": {
            "stale_s": rules.stale_s,
            "options_market_s": rules.options_market_s,
            "options_limit_s": rules.options_limit_s,
            "default_market_s": rules.default_market_s,
            "default_limit_s": rules.default_limit_s,
        },
        "count": len(results),
        "results": results,
    }


