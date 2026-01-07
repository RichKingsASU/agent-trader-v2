from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SafetyException(RuntimeError):
    def __init__(self, message: str, *, reason_codes: list[str]):
        super().__init__(message)
        self.reason_codes = reason_codes


@dataclass(frozen=True)
class SafetyState:
    trading_enabled: bool
    kill_switch: bool
    marketdata_fresh: bool
    marketdata_last_ts: datetime | None
    reason_codes: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=_utc_now)
    ttl_seconds: int = 30


def evaluate_safety_state(
    *,
    trading_enabled: bool = True,
    kill_switch: bool,
    marketdata_last_ts: datetime | None,
    stale_threshold_seconds: int,
    now: datetime | None = None,
    ttl_seconds: int = 30,
) -> SafetyState:
    """
    Evaluate the global safety state (single-source-of-truth logic).

    Strict rules:
    - kill_switch == True => NOT safe
    - marketdata_last_ts missing => NOT safe
    - now - marketdata_last_ts > stale_threshold_seconds => NOT safe (marketdata_fresh=False)
    - missing/unknown inputs should bias to NOT safe (callers should pass safe defaults)
    """
    t_now = now.astimezone(timezone.utc) if isinstance(now, datetime) else _utc_now()
    reasons: list[str] = []

    if not trading_enabled:
        reasons.append("trading_disabled")

    if kill_switch:
        reasons.append("kill_switch_enabled")

    fresh = False
    if marketdata_last_ts is None:
        reasons.append("marketdata_last_ts_missing")
    else:
        ts = marketdata_last_ts.replace(tzinfo=timezone.utc) if marketdata_last_ts.tzinfo is None else marketdata_last_ts.astimezone(timezone.utc)
        age_s = (t_now - ts).total_seconds()
        if age_s > float(stale_threshold_seconds):
            reasons.append("marketdata_stale")
            fresh = False
        else:
            fresh = True

    return SafetyState(
        trading_enabled=bool(trading_enabled),
        kill_switch=bool(kill_switch),
        marketdata_fresh=bool(fresh),
        marketdata_last_ts=marketdata_last_ts,
        reason_codes=reasons,
        updated_at=t_now,
        ttl_seconds=int(ttl_seconds),
    )


def is_safe_to_run_strategies(state: SafetyState) -> bool:
    return bool(state.trading_enabled) and (not state.kill_switch) and bool(state.marketdata_last_ts) and bool(state.marketdata_fresh)


def assert_safe_to_run(state: SafetyState) -> None:
    if is_safe_to_run_strategies(state):
        return
    codes = list(state.reason_codes or [])
    raise SafetyException("unsafe_to_run_strategies", reason_codes=codes)


def merge_reason_codes(*parts: Iterable[str]) -> list[str]:
    out: list[str] = []
    for p in parts:
        for code in p:
            c = str(code).strip()
            if not c:
                continue
            if c not in out:
                out.append(c)
    return out

