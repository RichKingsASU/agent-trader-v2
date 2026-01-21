from backend.common.secrets import get_secret
from backend.streams.alpaca_env import load_alpaca_env
from backend.common.config import _parse_bool
from backend.common.lifecycle import get_agent_lifecycle_details
from backend.common.agent_mode import read_agent_mode
from backend.common.runtime_fingerprint import get_runtime_fingerprint

from backend.common.agent_mode_guard import AgentModeGuard
from backend.common.kill_switch import KillSwitch
from backend.common.execution_confirm import ExecutionConfirm

import os
import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, TypeVar

from fastapi import FastAPI, HTTPException, Request, Response
from google.cloud import firestore

from backend.common.logging import init_structured_logging
from backend.common.logging import install_fastapi_request_id_middleware
from backend.common.logging import log_standard_event
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
        self.tenant_id: Optional[str] = kwargs.get("tenant_id")
        self.uid: Optional[str] = kwargs.get("uid")

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

        self.is_paused = _parse_env_bool("EXECUTION_HALTED", default=False)
        self.kill_switch_active = _parse_env_bool("EXEC_KILL_SWITCH", default=False)
        self.halted_doc = str(kwargs.get("execution_halted_doc") or "").strip().strip("/")
        self.kill_switch_doc = str(kwargs.get("exec_kill_switch_doc") or "").strip().strip("/")

        self.max_daily_trades = kwargs.get("max_daily_trades")
        self.max_daily_capital_pct = kwargs.get("max_daily_capital_pct")

        self.budgets_enabled = _parse_bool(os.getenv("EXEC_AGENT_BUDGETS_ENABLED") or "false")
        self.budgets_use_firestore = _parse_bool(os.getenv("EXEC_AGENT_BUDGETS_USE_FIRESTORE") or "true")
        self.budgets_fail_open = _parse_bool(os.getenv("EXEC_AGENT_BUDGETS_FAIL_OPEN") or "false")
        self.budget_cache_s = float(os.getenv("EXEC_AGENT_BUDGET_CACHE_S") or DEFAULT_BUDGET_CACHE_S)
        self.budgets_json = kwargs.get("execution_budgets_json")

        self.idempotency_store_id = str(os.getenv("EXEC_IDEMPOTENCY_STORE_ID") or "").strip() or None
        self.idempotency_store_key = str(os.getenv("EXEC_IDEMPOTENCY_STORE_KEY") or "").strip() or None

        self.execution_confirm_token = str(os.getenv("EXECUTION_CONFIRM_TOKEN") or "").strip()

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
        self.alpaca_base_url = get_secret("APCA_API_BASE_URL", fail_if_missing=False) or "https://paper-api.alpaca.markets"

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
        if self.tenant_id and (agent_name or os.getenv("AGENT_NAME") or "").strip():
            self.replay_context = ReplayContext(
                agent_name=agent_name or os.getenv("AGENT_NAME") or "execution-engine",
                agent_id=self.tenant_id, # Legacy mapping from tenant_id to agent_id
                run_id=self.tenant_id, # Legacy mapping
            )

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

def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    return bool(raw) == True if raw in {"1", "true", "t", "yes", "y", "on"} else default

def _parse_float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)

def _parse_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)

def _get_required_secret(name: str, default: Any = None, *, fail_if_missing: bool = True) -> str:
    """
    Read a secret value. Prefer Secret Manager, fallback to env var if allowed.
    """
    # Default fallback policy is OFF unless explicitly enabled.
    allow_fallback = _parse_bool_env("ALLOW_ENV_SECRET_FALLBACK", default=False)

    # DATABASE_URL is explicitly forbidden from falling back to env.
    if name == "DATABASE_URL" and allow_fallback:
        allow_fallback = False

    try:
        # Try Secret Manager first.
        val = get_secret(name, fail_if_missing=False)
        if val:
            return val
    except Exception:
        # If Secret Manager lookup fails, check if fallback is allowed.
        if not allow_fallback or name == "DATABASE_URL":
            raise

    # Fallback to environment variable if allowed.
    env_val = os.getenv(name)
    if env_val is not None:
        return str(env_val).strip()

    # If not found in SM or env, and required, raise error.
    if fail_if_missing:
        raise RuntimeError(f"Missing required secret or env var: {name}")
    return ""

def _get_secret_or_env(name: str, default: str = "", *, fail_if_missing: bool = True) -> str:
    """
    Read secret from Secret Manager or environment variable.
    """
    try:
        val = get_secret(name, fail_if_missing=False)
        if val:
            return val
    except Exception as e:
        # Log error accessing secret manager but proceed to env fallback if allowed.
        # The `get_secret` function already handles specific exceptions.
        # This catch is more for unexpected issues.
        pass

    # Fallback to environment variable.
    return os.getenv(name, default)

# --- Specific Secret Retrievers ---

def get_execution_confirm_token(*, required: bool = False) -> str:
    return _get_required_secret("EXECUTION_CONFIRM_TOKEN", default="", required=required)

def get_idempotency_store_id(*, required: bool = False) -> str:
    return _get_secret_or_env("EXEC_IDEMPOTENCY_STORE_ID", default="", required=required)

def get_idempotency_store_key(*, required: bool = False) -> str:
    return _get_secret_or_env("EXEC_IDEMPOTENCY_STORE_KEY", default="", required=required)

def get_tenant_id(*, required: bool = False) -> str:
    """
    Tenant ID for multi-tenant systems. Can be fetched from Secret Manager or env var.
    """
    return _get_secret_or_env("TENANT_ID", default="", required=required) or \
           _get_secret_or_env("EXEC_TENANT_ID", default="", required=required)

def get_uid(*, required: bool = False) -> str:
    """
    User ID for impersonation or specific operations.
    """
    return _get_secret_or_env("USER_ID", default="", required=required) or \
           _get_secret_or_env("EXEC_UID", default="", required=required)

def get_postgres_url(*, required: bool = True) -> str:
    """
    Postgres connection string. REQUIRED to be fetched from Secret Manager.
    Environment fallback is explicitly forbidden.
    """
    return get_secret("DATABASE_URL", fail_if_missing=required)

def get_firestore_project_id(*, required: bool = False) -> str:
    """
    Firestore project ID. Attempt to retrieve from Secret Manager, fallback to common env vars.
    """
    # Try Secret Manager first.
    pid = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
    if not pid:
        # Fallback to non-secret env vars.
        pid = get_env("GOOGLE_CLOUD_PROJECT", default=None, required=False)
    if not pid:
        pid = get_env("GCP_PROJECT", default=None, required=False)
    if not pid:
        pid = get_env("FIREBASE_PROJECT_ID", default=None, required=False)

    if pid:
        return str(pid)
    if required:
        raise RuntimeError("Missing required secret/env var: FIRESTORE_PROJECT_ID (or GOOGLE_CLOUD_PROJECT / GCP_PROJECT / FIREBASE_PROJECT_ID")
    return ""

def set_replay_context(*, agent_name: str | None = None):
    """
    Set replay context based on tenant_id and agent_name.
    """
    # Intentionally uses os.getenv for tenant_id and agent_name here,
    # assuming they are operational config, not secrets. If they are secrets, 
    # their retrieval should be updated to use get_secret.
    tenant_id = str(os.getenv("TENANT_ID") or "").strip() or None
    agent_name = str(agent_name or os.getenv("AGENT_NAME") or "").strip() or None

    if tenant_id and agent_name:
        app.state.replay_context = ReplayContext(
            agent_name=agent_name,
            agent_id=tenant_id, # Legacy mapping from tenant_id to agent_id
            run_id=tenant_id, # Legacy mapping
        )
    else:
        app.state.replay_context = None

def _get_dynamically_configured_secrets() -> dict[str, str]:
    """
    Dynamically fetches secrets based on configuration.
    Used for secrets that are only conditionally required or have complex naming.
    """
    secrets: Dict[str, str] = {}
    # Example: dynamically fetch a secret if a certain env var is set.
    # if _parse_env_bool("FETCH_DYNAMIC_SECRET_X"):
    #     secrets["dynamic_secret_x"] = get_secret("DYNAMIC_SECRET_X", fail_if_missing=False) or ""
    return secrets

def get_all_secrets_for_config(app_state: Any) -> Dict[str, str]:
    """
    Aggregates all secrets for application configuration.
    """
    all_secrets = {}

    # Core credentials/endpoints managed by secrets.py
    # Note: DATABASE_URL is mandatory and cannot fall back to env.
    all_secrets["DATABASE_URL"] = get_secret("DATABASE_URL", fail_if_missing=True)

    # Alpaca credentials and base URL
    all_secrets["APCA_API_KEY_ID"] = get_secret("APCA_API_KEY_ID", fail_if_missing=False)
    all_secrets["APCA_API_SECRET_KEY"] = get_secret("APCA_API_SECRET_KEY", fail_if_missing=False)
    all_secrets["APCA_API_BASE_URL"] = get_secret("APCA_API_BASE_URL", fail_if_missing=False) or "https://paper-api.alpaca.markets"

    # Other potential secrets
    all_secrets["TENANT_ID"] = get_secret("TENANT_ID", fail_if_missing=False)
    all_secrets["EXEC_TENANT_ID"] = get_secret("EXEC_TENANT_ID", fail_if_missing=False)
    all_secrets["USER_ID"] = get_secret("USER_ID", fail_if_missing=False)
    all_secrets["EXEC_UID"] = get_secret("EXEC_UID", fail_if_missing=False)

    all_secrets["FIREBASE_PROJECT_ID"] = get_secret("FIREBASE_PROJECT_ID", fail_if_missing=False)
    all_secrets["FIRESTORE_PROJECT_ID"] = get_secret("FIRESTORE_PROJECT_ID", fail_if_missing=False)
    all_secrets["EXECUTION_CONFIRM_TOKEN"] = get_secret("EXECUTION_CONFIRM_TOKEN", fail_if_missing=False)
    all_secrets["EXEC_IDEMPOTENCY_STORE_ID"] = get_secret("EXEC_IDEMPOTENCY_STORE_ID", fail_if_missing=False)
    all_secrets["EXEC_IDEMPOTENCY_STORE_KEY"] = get_secret("EXEC_IDEMPOTENCY_STORE_KEY", fail_if_missing=False)

    # Dynamically fetched secrets
    all_secrets.update(_get_dynamically_configured_secrets())

    # Add application-specific secrets if any (e.g., from app_state)
    # This part might need to be adapted based on how app_state is populated.
    # Example: if app_state contains secrets, they could be merged here.

    return all_secrets

def get_all_secrets_for_app_state(app_state: Any) -> Dict[str, str]:
    """
    Aggregates secrets relevant for the app state, prioritizing app_state secrets
    if they exist, otherwise falling back to global secrets.
    """
    # Global secrets fetched from Secret Manager or fallback env vars.
    global_secrets = get_all_secrets_for_config(app_state=app_state)

    # Application-specific secrets might be stored directly in app_state if loaded differently.
    # For now, assume all secrets are globally accessible via get_all_secrets_for_config.
    # If app_state contains secrets directly, merge them here, potentially overriding global_secrets.
    # For simplicity, we'll use global secrets for now.
    return global_secrets