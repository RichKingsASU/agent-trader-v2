from backend.common.secrets import get_secret
from backend.streams.alpaca_env import load_alpaca_env
from backend.common.config import _parse_bool, _as_int_or_none, _as_float_or_none, _require_env_string
from backend.common.lifecycle import get_agent_lifecycle_details
from backend.common.agent_mode import read_agent_mode
from backend.common.runtime_fingerprint import get_runtime_fingerprint

from backend.common.agent_mode_guard import AgentModeGuard
from backend.common.kill_switch import KillSwitch
from backend.common.execution_confirm import ExecutionConfirm
from backend.common.replay_context import ReplayContext # Assuming ReplayContext is available here

import os
import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, TypeVar

from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import firestore

from backend.common.logging import init_structured_logging, log_standard_event
from backend.observability.correlation import bind_correlation_id, get_or_create_correlation_id

SERVICE_NAME = os.getenv("SERVICE_NAME", "execution-engine")
ENV = os.getenv("ENV", "prod")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

init_structured_logging(service=SERVICE_NAME, env=ENV, level=LOG_LEVEL)
logger = logging.getLogger(__name__)

# --- Shared constants ---
DEFAULT_MAX_DAILY_TRADES = 100
DEFAULT_MAX_DAILY_CAPITAL_PCT = 0.01
DEFAULT_BUDGET_CACHE_S = 60.0

# --- Execution Engine Configuration ---
class ExecutionEngineConfig:
    def __init__(self, **kwargs: Any) -> None:
        # Use get_secret for tenant_id and uid, with fallbacks if necessary but prioritizing secrets.
        self.tenant_id: Optional[str] = kwargs.get("tenant_id") or get_secret("EXEC_TENANT_ID", fail_if_missing=False) or get_secret("TENANT_ID", fail_if_missing=False)
        self.uid: Optional[str] = kwargs.get("uid") or get_secret("EXEC_UID", fail_if_missing=False) or get_secret("USER_ID", fail_if_missing=False)

        self.agent_name: str = kwargs.get("agent_name", "execution-engine")
        self.agent_role: str = kwargs.get("agent_role", "execution")
        self.agent_mode: str = kwargs.get("agent_mode", read_agent_mode())
        self.git_sha: Optional[str] = kwargs.get("git_sha")
        self.build_id: Optional[str] = kwargs.get("build_id")

        # Runtime lifecycle details.
        self.lifecycle = get_agent_lifecycle_details(
            agent_name=self.agent_name,
            agent_mode=self.agent_mode,
            git_sha=self.git_sha,
            build_id=self.build_id,
        )

        self.is_paused = _parse_bool_env("EXECUTION_HALTED", default=False)
        self.kill_switch_active = _parse_bool_env("EXEC_KILL_SWITCH", default=False)
        self.halted_doc = str(kwargs.get("execution_halted_doc") or "").strip().strip("/")
        self.kill_switch_doc = str(kwargs.get("exec_kill_switch_doc") or "").strip().strip("/")

        self.max_daily_trades = kwargs.get("max_daily_trades")
        self.max_daily_capital_pct = kwargs.get("max_daily_capital_pct")

        self.budgets_enabled = _parse_bool_env("EXEC_AGENT_BUDGETS_ENABLED", default=False)
        self.budgets_use_firestore = _parse_bool_env("EXEC_AGENT_BUDGETS_USE_FIRESTORE", default=True)
        self.budgets_fail_open = _parse_bool_env("EXEC_AGENT_BUDGETS_FAIL_OPEN", default=False)
        self.budget_cache_s = float(os.getenv("EXEC_AGENT_BUDGET_CACHE_S") or DEFAULT_BUDGET_CACHE_S)
        self.budgets_json = kwargs.get("execution_budgets_json")

        self.idempotency_store_id = str(_get_secret_or_env("EXEC_IDEMPOTENCY_STORE_ID", default="")).strip() or None
        self.idempotency_store_key = str(_get_secret_or_env("EXEC_IDEMPOTENCY_STORE_KEY", default="")).strip() or None

        self.execution_confirm_token = str(get_secret("EXECUTION_CONFIRM_TOKEN", default="")).strip()

        self.max_future_skew_s = float(os.getenv("STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS") or "5")

        self.postgres_url = get_secret("DATABASE_URL", fail_if_missing=True) # Treat as secret
        self.firestore_project_id = get_secret("FIREBASE_PROJECT_ID", fail_if_missing=True) # Treat as secret
        self.firestore_emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST") # Config, not secret

        self.idempotency_ttl_minutes = int(os.getenv("INTENT_TTL_MINUTES") or "5")
        if str(os.getenv("INTENT_TTL_MINUTES") or "").strip().isdigit():
            self.idempotency_ttl_minutes = int(os.getenv("INTENT_TTL_MINUTES"))

        self.max_trades_per_day = _as_int_or_none(os.getenv("EXEC_MAX_DAILY_TRADES"))
        self.max_daily_capital_pct = _as_float_or_none(os.getenv("EXEC_MAX_DAILY_CAPITAL_PCT"))

        self.replay_context = None
        if self.tenant_id and (os.getenv("AGENT_NAME") or "").strip():
            self.replay_context = ReplayContext(
                agent_name=os.getenv("AGENT_NAME") or "execution-engine",
                agent_id=self.tenant_id, # Legacy mapping from tenant_id to agent_id
                run_id=self.tenant_id, # Legacy mapping
            )
        self.set_replay_context(agent_name=os.getenv("AGENT_NAME") or "execution-engine")

        self.trader_type = str(os.getenv("TRADER_TYPE", "")).strip().upper() or "LOCAL"
        self.trading_mode = str(os.getenv("TRADING_MODE", "")).strip().lower()
        self.execution_mode = str(os.getenv("EXECUTION_MODE", "INTENT_ONLY")).strip().upper()

        # --- Alpaca ---
        self.alpaca_api_key = get_secret("APCA_API_KEY_ID")
        self.alpaca_secret_key = get_secret("APCA_API_SECRET_KEY")
        self.alpaca_base_url = get_secret("APCA_API_BASE_URL", default="https://paper-api.alpaca.markets")

        # --- Check for contradictory settings ---
        if self.trading_mode == "live" and self.alpaca_base_url == "https://paper-api.alpaca.markets":
            raise ValueError("TRADING_MODE=live but APCA_API_BASE_URL is set to paper")

        self.broker_alpaca_config = self.to_broker_alpaca_config()

    def to_broker_alpaca_config(self) -> Dict[str, Any]:
        return {
            "APCA_API_KEY_ID": self.alpaca_api_key,
            "APCA_API_SECRET_KEY": self.alpaca_secret_key,
            "APCA_API_BASE_URL": self.alpaca_base_url,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "uid": self.uid,
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_mode": self.agent_mode,
            "git_sha": self.git_sha,
            "build_id": self.build_id,
            "lifecycle": self.lifecycle,
            "is_paused": self.is_paused,
            "kill_switch_active": self.kill_switch_active,
            "halted_doc": self.halted_doc,
            "kill_switch_doc": self.kill_switch_doc,
            "max_daily_trades": self.max_daily_trades,
            "max_daily_capital_pct": self.max_daily_capital_pct,
            "budgets_enabled": self.budgets_enabled,
            "budgets_use_firestore": self.budgets_use_firestore,
            "budgets_fail_open": self.budgets_fail_open,
            "budget_cache_s": self.budget_cache_s,
            "budgets_json": self.budgets_json,
            "idempotency_store_id": self.idempotency_store_id,
            "idempotency_store_key": self.idempotency_store_key,
            "execution_confirm_token": self.execution_confirm_token,
            "max_future_skew_s": self.max_future_skew_s,
            "postgres_url": self.postgres_url,
            "firestore_project_id": self.firestore_project_id,
            "firestore_emulator_host": self.firestore_emulator_host,
            "idempotency_ttl_minutes": self.idempotency_ttl_minutes,
            "trader_type": self.trader_type,
            "trading_mode": self.trading_mode,
            "execution_mode": self.execution_mode,
            "alpaca_broker_config": self.to_broker_alpaca_config(),
        }

    def set_replay_context(self, *, agent_name: str | None = None):
        if self.tenant_id and (os.getenv("AGENT_NAME") or "").strip():
            self"agent_name": str(os.getenv("AGENT_NAME") or "execution-engine").strip() or "execution-engine",
            "agent_id": self.tenant_id, # Legacy mapping from tenant_id to agent_id
            "run_id": self.tenant_id, # Legacy mapping
        )
    else:
        self.replay_context = None

def _as_int_or_none(v: str | None) -> int | None:
    try:
        return int(v)
    except Exception:
        return None

def _as_float_or_none(v: str | None) -> float | None:
    try:
        return float(v)
    except Exception:
        return None

    def kill_switch_enabled(self) -> bool:
        """
        Returns True if the execution kill-switch is enabled.

        This is a public wrapper around the internal kill-switch checks so
        execution agents can gate trading before attempting order routing.
        """
        return self._kill_switch_enabled()

    def _kill_switch_enabled(self) -> bool:
        # Standard global kill switch (env + optional file mount).
        if is_kill_switch_enabled():
            return True

        # Optional Firestore-backed kill switch (legacy; keep for back-compat).
        try:
            path = str(os.getenv("EXECUTION_HALTED_DOC") or os.getenv("EXEC_KILL_SWITCH_DOC") or "").strip().strip("/")
            if not path:
                return False
            parts = path.split("/")
            if len(parts) != 2:
                logger.warning("Invalid kill switch doc path: %s", path)
                return False
            col, doc = parts
            from backend.persistence.firebase_client import get_firestore_client

            db = get_firestore_client()
            snap = db.collection(col).document(doc).get()
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            return bool(data.get("enabled") is True)
        except Exception:
            return False

    def validate(self, *, intent: OrderIntent) -> RiskDecision:
        intent = intent.normalized()
        checks: list[dict[str, Any]] = []

        # Hard invariants (crash loud on internal inconsistencies).
        _enforce_risk_invariants_from_intent(intent=intent)

        # Kill switch
        enabled = self.kill_switch_enabled()
        checks.append({"check": "kill_switch", "enabled": enabled})
        if enabled:
            return RiskDecision(allowed=False, reason="kill_switch_enabled", checks=checks)

        # Loss acceleration guard (rolling drawdown velocity)
        # Operates independently of strategy logic: pure risk gate on intent routing.
        try:
            uid = str(intent.metadata.get("uid") or intent.metadata.get("user_id") or os.getenv("EXEC_UID") or "").strip() or None
            guard = LossAccelerationGuard()
            decision = guard.decide(uid=uid)
            m = decision.metrics
            checks.append(
                {
                    "check": "loss_acceleration_guard",
                    "action": decision.action,
                    "reason": decision.reason,
                    "uid": uid,
                    "metrics": (
                        {
                            "window_seconds": m.window_seconds,
                            "points_used": m.points_used,
                            "hwm_equity": m.hwm_equity,
                            "current_equity": m.current_equity,
                            "current_drawdown_pct": m.current_drawdown_pct,
                            "velocity_pct_per_min": m.velocity_pct_per_min,
                            "window_start": m.window_start.isoformat(),
                            "window_end": m.window_end.isoformat(),
                        }
                        if m is not None
                        else None
                    ),
                    "retry_after_seconds": decision.retry_after_seconds,
                    "pause_until": decision.pause_until.isoformat() if decision.pause_until else None,
                }
            )
            if decision.action in {"pause", "throttle"}:
                return RiskDecision(allowed=False, reason=decision.reason or "loss_acceleration", checks=checks)
        except Exception as e:
            # Best-effort: never block if telemetry/reads fail.
            checks.append({"check": "loss_acceleration_guard", "error": str(e)})

        # Daily trades
        try:
            if self._ledger is None:
                self._ledger = _FirestoreLedger()
            today = _iso_date_utc()

            tenant_id: Optional[str] = None
            try:
                # Tenant-scoped ledger (preferred).
                tenant_id = self._ledger._resolve_tenant_id(intent=intent)  # type: ignore[attr-defined]
            except Exception:
                tenant_id = None

            # Back-compat: allow injected ledger stubs that don't take tenant_id.
            try:
                if tenant_id is not None:
                    trades_today = self._ledger.count_trades_today(
                        tenant_id=tenant_id,
                        broker_account_id=intent.broker_account_id,
                        trading_date=today,
                    )
                else:
                    trades_today = self._ledger.count_trades_today(
                        broker_account_id=intent.broker_account_id,
                        trading_date=today,
                    )
            except TypeError:
                trades_today = self._ledger.count_trades_today(
                    broker_account_id=intent.broker_account_id,
                    trading_date=today,
                )

            checks.append(
                {
                    "check": "max_daily_trades",
                    "today": today,
                    "trades_today": trades_today,
                    "limit": self._config.max_daily_trades,
                }
            )
            if tenant_id is not None:
                checks[-1]["tenant_id"] = tenant_id
            if trades_today >= self._config.max_daily_trades:
                return RiskDecision(allowed=False, reason="max_daily_trades_exceeded", checks=checks)
        except Exception as e:
            checks.append({"check": "max_daily_trades", "error": str(e)})
            if not self._config.fail_open:
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        # Position size
        try:
            from backend.common.secrets import get_database_url  # noqa: WPS433

            database_url = get_database_url(required=True)
            if self._positions is None and database_url:
                self._positions = _PostgresPositions(database_url=database_url)
            if self._positions is None:
                raise RuntimeError("positions provider not configured (set DATABASE_URL)")

            current_qty = self._positions.get_position_qty(symbol=intent.symbol)
            projected_qty = current_qty + (intent.qty if intent.side == "buy" else -intent.qty)
            checks.append(
                {
                    "check": "max_position_size",
                    "symbol": intent.symbol,
                    "current_qty": current_qty,
                    "projected_qty": projected_qty,
                    "limit_abs_qty": self._config.max_position_qty,
                }
            )
            if abs(projected_qty) > self._config.max_position_qty:
                return RiskDecision(allowed=False, reason="max_position_size_exceeded", checks=checks)
        except Exception as e:
            checks.append({"check": "max_position_size", "error": str(e)})
            if not self._config.fail_open:
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        # Enforce max_risk_per_trade if provided (soft-fail via rejection),
        # but ALSO treat "allowed=True while exceeding" as a postcondition violation below.
        try:
            md = dict(intent.metadata or {})
            if "max_risk_per_trade" in md and "proposed_trade_risk" in md:
                max_risk_per_trade = _as_money_decimal(md.get("max_risk_per_trade"), name="max_risk_per_trade")
                proposed_trade_risk = _as_money_decimal(md.get("proposed_trade_risk"), name="proposed_trade_risk")
                checks.append(
                    {
                        "check": "max_risk_per_trade",
                        "max_risk_per_trade": float(max_risk_per_trade),
                        "proposed_trade_risk": float(proposed_trade_risk),
                    }
                )
                if proposed_trade_risk > max_risk_per_trade:
                    return RiskDecision(allowed=False, reason="max_risk_per_trade_exceeded", checks=checks)
        except InvariantViolation:
            # If metadata is malformed for risk checking, that's an invariant breach.
            raise
        except Exception as e:
            checks.append({"check": "max_risk_per_trade", "error": str(e)})
            if not self._config.fail_open:
                return RiskDecision(allowed=False, reason="risk_data_unavailable", checks=checks)

        # Postcondition (crash loudly if a bypass is possible):
        # If we say "allowed", then max_risk_per_trade MUST be satisfied when provided.
        md = dict(intent.metadata or {})
        if "max_risk_per_trade" in md and "proposed_trade_risk" in md:
            max_risk_per_trade = _as_money_decimal(md.get("max_risk_per_trade"), name="max_risk_per_trade")
            proposed_trade_risk = _as_money_decimal(md.get("proposed_trade_risk"), name="proposed_trade_risk")
            if proposed_trade_risk > max_risk_per_trade:
                _fail_invariant(
                    name="max_risk_per_trade_enforced",
                    message=(
                        f"risk.allowed=True would violate max_risk_per_trade "
                        f"({proposed_trade_risk} > {max_risk_per_trade})"
                    ),
                    context={
                        "max_risk_per_trade": max_risk_per_trade,
                        "proposed_trade_risk": proposed_trade_risk,
                        "symbol": intent.symbol,
                        "strategy_id": intent.strategy_id,
                        "client_intent_id": intent.client_intent_id,
                    },
                )

        return RiskDecision(allowed=True, reason="ok", checks=checks)


@dataclass(frozen=True)
class ExecutionResult:
    status: str  # "rejected" | "accepted" | "placed" | "dry_run" | "downgraded"
    risk: RiskDecision
    broker_order_id: Optional[str] = None
    broker_order: Optional[dict[str, Any]] = None
    message: Optional[str] = None
    routing: Optional[SmartRoutingDecision] = None  # Smart routing analysis

def _require_env_string(name: str, default: Optional[str] = None) -> str:
    v = (os.getenv(name) or "").strip()
    if not v:
        if default is not None:
            return default
        raise RuntimeError(f"Missing required env var: {name}")
    return v

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