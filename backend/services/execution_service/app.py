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
    required = str(os.getenv("EXEC_AGENT_ADMIN_KEY") or "").strip()
    if not required:
        # Hide the endpoint unless explicitly enabled.
        raise HTTPException(status_code=404, detail="not_found")
    provided = str(request.headers.get("X-Exec-Agent-Key") or "").strip()
    if provided != required:
        raise HTTPException(status_code=401, detail="unauthorized")

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
    required = str(os.getenv("EXEC_AGENT_ADMIN_KEY") or "").strip()
    if required:
        provided = str(request.headers.get("X-Exec-Agent-Key") or "").strip()
        if provided != required:
            raise HTTPException(status_code=401, detail="unauthorized")

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
    # Thread an explicit execution confirmation token into the intent metadata.
    # This ensures downstream broker execution cannot be triggered without an operator-supplied token.
    md = dict(req.metadata or {})
    header_token = str(request.headers.get("X-Exec-Confirm-Token") or "").strip()
    if header_token:
        md["exec_confirm_token"] = header_token

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
        metadata=md,
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


