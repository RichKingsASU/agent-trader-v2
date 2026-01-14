from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from backend.time.nyse_time import NYSE_TZ, to_nyse, market_open_dt, is_trading_day


def _bool_env(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    return int(v)


@dataclass(frozen=True, slots=True)
class MarketOpenGuardConfig:
    """
    Guardrail: block trading during the first N minutes after regular-session open.

    Env overrides:
    - EXEC_MARKET_OPEN_COOLDOWN_MINUTES: int minutes to block after open (default 15; <=0 disables)
    - EXEC_MARKET_OPEN_GUARD_ENABLED: truthy/falsey toggle (default true)
    """

    enabled: bool = True
    cooldown_minutes: int = 15

    @staticmethod
    def from_env() -> "MarketOpenGuardConfig":
        enabled = _bool_env("EXEC_MARKET_OPEN_GUARD_ENABLED", True)
        cooldown_minutes = _int_env("EXEC_MARKET_OPEN_COOLDOWN_MINUTES", 15)
        if cooldown_minutes < 0:
            cooldown_minutes = 0
        return MarketOpenGuardConfig(enabled=enabled, cooldown_minutes=cooldown_minutes)


@dataclass(frozen=True, slots=True)
class MarketOpenGuardDecision:
    allowed: bool
    reason: str
    now_ny_iso: Optional[str] = None
    open_ny_iso: Optional[str] = None
    cooldown_minutes: Optional[int] = None
    seconds_until_allowed: Optional[int] = None


class MarketOpenGuard:
    def __init__(self, *, config: MarketOpenGuardConfig | None = None):
        self._cfg = config or MarketOpenGuardConfig.from_env()

    def decide(self, *, now_utc: datetime) -> MarketOpenGuardDecision:
        """
        Decide whether trading is allowed at `now_utc` (tz-aware UTC datetime).

        Blocks only during regular-session open cooldown window; does not attempt to
        block pre-market or after-hours trading.
        """

        if not self._cfg.enabled:
            return MarketOpenGuardDecision(allowed=True, reason="disabled")
        if self._cfg.cooldown_minutes <= 0:
            return MarketOpenGuardDecision(allowed=True, reason="cooldown_minutes_disabled")

        now_ny = to_nyse(now_utc)
        d = now_ny.date()
        if not is_trading_day(d):
            return MarketOpenGuardDecision(
                allowed=True,
                reason="not_trading_day",
                now_ny_iso=now_ny.isoformat(),
                cooldown_minutes=self._cfg.cooldown_minutes,
            )

        open_ny = market_open_dt(d)
        # Only enforce after (or at) open; if it's pre-open, we don't block.
        if now_ny < open_ny:
            return MarketOpenGuardDecision(
                allowed=True,
                reason="pre_open",
                now_ny_iso=now_ny.isoformat(),
                open_ny_iso=open_ny.isoformat(),
                cooldown_minutes=self._cfg.cooldown_minutes,
            )

        cooldown_end = open_ny + timedelta(minutes=int(self._cfg.cooldown_minutes))
        if now_ny < cooldown_end:
            seconds_left = int((cooldown_end - now_ny).total_seconds())
            if seconds_left < 0:
                seconds_left = 0
            return MarketOpenGuardDecision(
                allowed=False,
                reason="market_open_cooldown",
                now_ny_iso=now_ny.isoformat(),
                open_ny_iso=open_ny.isoformat(),
                cooldown_minutes=self._cfg.cooldown_minutes,
                seconds_until_allowed=seconds_left,
            )

        return MarketOpenGuardDecision(
            allowed=True,
            reason="ok",
            now_ny_iso=now_ny.isoformat(),
            open_ny_iso=open_ny.isoformat(),
            cooldown_minutes=self._cfg.cooldown_minutes,
        )


__all__ = [
    "MarketOpenGuard",
    "MarketOpenGuardConfig",
    "MarketOpenGuardDecision",
    "NYSE_TZ",
]

