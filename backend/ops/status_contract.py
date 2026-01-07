"""
Ops Status Contract (single stable JSON schema).

This module is intentionally dependency-light and safe to call from any service.
It must NEVER enable trading or mutate system state.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


OPS_STATE = Literal["OK", "DEGRADED", "HALTED", "MARKET_CLOSED", "OFFLINE", "UNKNOWN"]
SERVICE_KIND = Literal["marketdata", "strategy", "execution", "ingest", "ops"]


REASON_KILL_SWITCH = "KILL_SWITCH"
REASON_MARKET_CLOSED = "MARKET_CLOSED"
REASON_MARKETDATA_STALE = "MARKETDATA_STALE"
REASON_MARKETDATA_MISSING = "MARKETDATA_MISSING"
REASON_EXECUTION_DISABLED = "EXECUTION_DISABLED"
REASON_HEARTBEAT_STALE = "HEARTBEAT_STALE"
REASON_REQUIRED_FIELDS_MISSING = "REQUIRED_FIELDS_MISSING"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _age_seconds(*, now_utc: datetime, then_utc: Optional[datetime]) -> Optional[float]:
    if then_utc is None:
        return None
    if then_utc.tzinfo is None:
        then_utc = then_utc.replace(tzinfo=timezone.utc)
    return max(0.0, (now_utc - then_utc.astimezone(timezone.utc)).total_seconds())


def is_nyse_market_hours(*, now_utc: Optional[datetime] = None) -> bool:
    """
    Minimal NYSE market-hours check:
    - Weekdays only (Mon-Fri)
    - 09:30–16:00 America/New_York

    Notes:
    - This intentionally ignores holidays/half-days.
    - If a canonical nyse_time module exists in the repo later, migrate to it.
    """

    now = now_utc or utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if ZoneInfo is None:  # pragma: no cover
        # Worst-case fallback (no tz database): treat as market open to avoid false MARKET_CLOSED.
        return True

    ny_tz = ZoneInfo("America/New_York")
    ny = now.astimezone(ny_tz)
    if ny.weekday() >= 5:
        return False

    open_t = time(9, 30)
    close_t = time(16, 0)
    t = ny.timetz().replace(tzinfo=None)
    return (t >= open_t) and (t <= close_t)


class AgentIdentity(BaseModel):
    agent_name: str
    agent_role: str
    agent_mode: str


class StatusBlock(BaseModel):
    state: OPS_STATE
    summary: str
    reason_codes: list[str] = Field(default_factory=list)
    last_updated_utc: str


class HeartbeatBlock(BaseModel):
    last_heartbeat_utc: Optional[str] = None
    age_seconds: Optional[float] = None
    ttl_seconds: int = 60


class MarketdataBlock(BaseModel):
    last_tick_utc: Optional[str] = None
    last_bar_utc: Optional[str] = None
    stale_threshold_seconds: int = 120
    is_fresh: Optional[bool] = None


class SafetyBlock(BaseModel):
    kill_switch: bool
    safe_to_run_strategies: bool
    safe_to_execute_orders: bool = False  # MUST remain false for now.
    gating_reasons: list[str] = Field(default_factory=list)


class EndpointsBlock(BaseModel):
    healthz: Optional[str] = None
    heartbeat: Optional[str] = None
    metrics: Optional[str] = None


class OpsStatus(BaseModel):
    # Required identity
    service_name: str
    service_kind: SERVICE_KIND
    repo_id: str
    git_sha: Optional[str] = None
    build_id: Optional[str] = None

    agent_identity: AgentIdentity

    # Deterministic surface
    status: StatusBlock
    heartbeat: HeartbeatBlock

    # Nullable / kind-specific
    marketdata: Optional[MarketdataBlock] = None

    safety: SafetyBlock
    endpoints: Optional[EndpointsBlock] = None


def compute_ops_state(
    *,
    service_kind: SERVICE_KIND,
    process_up: bool,
    kill_switch: bool,
    market_is_open: bool,
    required_fields_present: bool = True,
    heartbeat_age_seconds: Optional[float] = None,
    heartbeat_ttl_seconds: Optional[int] = None,
    marketdata_is_fresh: Optional[bool] = None,
    execution_enabled: Optional[bool] = None,
    execution_replicas: Optional[int] = None,
) -> tuple[OPS_STATE, list[str]]:
    """
    Truth-table computation for stable Ops UI semantics.

    Deterministic ordering:
    - Required-fields missing => UNKNOWN
    - process down (unless execution explicitly disabled/0) => OFFLINE
    - kill switch => HALTED
    - execution disabled/0 => OFFLINE
    - marketdata stale/missing during market hours => HALTED (strategy/execution) or DEGRADED (marketdata)
    - heartbeat stale => DEGRADED
    - market closed and healthy => MARKET_CLOSED
    - else OK
    """

    reasons: list[str] = []

    if not required_fields_present:
        return "UNKNOWN", [REASON_REQUIRED_FIELDS_MISSING]

    # Execution disabled/replicas=0 is "OFFLINE but not an error" even if the process isn't up.
    if service_kind == "execution":
        if execution_enabled is False or (execution_replicas is not None and int(execution_replicas) <= 0):
            return "OFFLINE", [REASON_EXECUTION_DISABLED]

    if not process_up:
        return "OFFLINE", ["PROCESS_DOWN"]

    if kill_switch:
        return "HALTED", [REASON_KILL_SWITCH]

    # Marketdata freshness: only meaningful during market hours.
    if market_is_open:
        if marketdata_is_fresh is False:
            reasons.append(REASON_MARKETDATA_STALE)
            if service_kind in ("strategy", "execution"):
                return "HALTED", reasons
            if service_kind == "marketdata":
                return "DEGRADED", reasons
            return "DEGRADED", reasons
        if marketdata_is_fresh is None and service_kind in ("strategy", "execution", "marketdata"):
            reasons.append(REASON_MARKETDATA_MISSING)
            if service_kind in ("strategy", "execution"):
                return "HALTED", reasons
            if service_kind == "marketdata":
                return "DEGRADED", reasons
            return "DEGRADED", reasons

    # Heartbeat TTL check (generic service heartbeat; separate from marketdata freshness).
    if heartbeat_age_seconds is not None and heartbeat_ttl_seconds is not None:
        if heartbeat_age_seconds > float(heartbeat_ttl_seconds):
            reasons.append(REASON_HEARTBEAT_STALE)
            return "DEGRADED", reasons

    # Avoid false degradation after-hours: MARKET_CLOSED should be calm when everything else is healthy.
    if not market_is_open and service_kind in ("marketdata", "strategy", "execution", "ingest"):
        return "MARKET_CLOSED", [REASON_MARKET_CLOSED]

    return "OK", reasons


def build_ops_status(
    *,
    service_name: str,
    service_kind: SERVICE_KIND,
    agent_identity: AgentIdentity,
    repo_id: str = "RichKingsASU/agent-trader-v2",
    git_sha: Optional[str] = None,
    build_id: Optional[str] = None,
    endpoints: Optional[EndpointsBlock] = None,
    # Inputs
    kill_switch: bool = False,
    process_up: bool = True,
    market_is_open: Optional[bool] = None,
    heartbeat_last_utc: Optional[datetime] = None,
    heartbeat_ttl_seconds: int = 60,
    marketdata_last_tick_utc: Optional[datetime] = None,
    marketdata_last_bar_utc: Optional[datetime] = None,
    marketdata_stale_threshold_seconds: int = 120,
    execution_enabled: Optional[bool] = None,
    execution_replicas: Optional[int] = None,
) -> OpsStatus:
    now = utc_now()
    market_open = market_is_open if market_is_open is not None else is_nyse_market_hours(now_utc=now)

    hb_last = heartbeat_last_utc or now
    hb_age = _age_seconds(now_utc=now, then_utc=hb_last)

    md_is_fresh: Optional[bool]
    if marketdata_last_tick_utc is None:
        md_is_fresh = None
    else:
        md_age = _age_seconds(now_utc=now, then_utc=marketdata_last_tick_utc)
        md_is_fresh = (md_age is not None) and (md_age <= float(marketdata_stale_threshold_seconds))

    required_fields_present = bool(service_name) and bool(service_kind) and bool(repo_id) and bool(agent_identity.agent_name)

    state, reason_codes = compute_ops_state(
        service_kind=service_kind,
        process_up=process_up,
        kill_switch=kill_switch,
        market_is_open=market_open,
        required_fields_present=required_fields_present,
        heartbeat_age_seconds=hb_age,
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        marketdata_is_fresh=md_is_fresh,
        execution_enabled=execution_enabled,
        execution_replicas=execution_replicas,
    )

    gating: list[str] = []
    if kill_switch:
        gating.append(REASON_KILL_SWITCH)
    if market_open and md_is_fresh is False:
        gating.append(REASON_MARKETDATA_STALE)
    if service_kind == "execution":
        gating.append("EXECUTION_ORDERS_DISABLED_CONTRACT")

    safe_to_run_strategies = (not kill_switch) and (not market_open or md_is_fresh is True or md_is_fresh is None)
    # MUST remain false for now (absolute rule).
    safe_to_execute_orders = False

    summary_map: dict[str, str] = {
        "OK": "Healthy",
        "DEGRADED": "Degraded",
        "HALTED": "Halted",
        "MARKET_CLOSED": "Market closed",
        "OFFLINE": "Offline",
        "UNKNOWN": "Unknown",
    }

    return OpsStatus(
        service_name=service_name,
        service_kind=service_kind,
        repo_id=repo_id,
        git_sha=git_sha,
        build_id=build_id,
        agent_identity=agent_identity,
        status=StatusBlock(
            state=state,
            summary=summary_map.get(state, state),
            reason_codes=reason_codes,
            last_updated_utc=_iso_utc(now) or "",
        ),
        heartbeat=HeartbeatBlock(
            last_heartbeat_utc=_iso_utc(hb_last),
            age_seconds=hb_age,
            ttl_seconds=int(heartbeat_ttl_seconds),
        ),
        marketdata=MarketdataBlock(
            last_tick_utc=_iso_utc(marketdata_last_tick_utc),
            last_bar_utc=_iso_utc(marketdata_last_bar_utc),
            stale_threshold_seconds=int(marketdata_stale_threshold_seconds),
            is_fresh=md_is_fresh,
        )
        if service_kind in ("marketdata", "strategy", "execution")
        else None,
        safety=SafetyBlock(
            kill_switch=bool(kill_switch),
            safe_to_run_strategies=bool(safe_to_run_strategies),
            safe_to_execute_orders=bool(safe_to_execute_orders),
            gating_reasons=gating,
        ),
        endpoints=endpoints,
    )

