"""
Strategy-local daily target halt guard.

Requirement:
- If daily_return_pct >= 0.04:
  - stop emitting new order intents
  - emit structured log: strategy.halted.daily_target

Notes:
- This module is intentionally "strategy logic only" (no execution changes).
- `daily_return_pct` is sourced from environment by default to keep the guard
  strategy-local and runtime-agnostic. Orchestrators can set DAILY_RETURN_PCT.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from typing import Optional

from backend.common.ops_log import log_json


DAILY_TARGET_RETURN_PCT = 0.04


def _parse_daily_return_pct(raw: str | None) -> Optional[float]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        v = float(s)
    except Exception:
        return None
    # Normalize: if caller accidentally provides "4" for 4%, treat as 0.04.
    if v > 1.0:
        v = v / 100.0
    return v


def read_daily_return_pct(*, env_var: str = "DAILY_RETURN_PCT") -> Optional[float]:
    """
    Best-effort read of daily_return_pct from environment.

    The value is expected to be a fraction (e.g. 0.04 for +4%).
    """
    return _parse_daily_return_pct(os.getenv(env_var))


@dataclass
class DailyTargetHaltLatch:
    """
    In-memory daily latch to avoid log spam.

    Resets automatically when the local calendar day changes.
    """

    _halted_day: Optional[date] = None
    _halted: bool = False

    def _reset_if_new_day(self, today: date) -> None:
        if self._halted_day != today:
            self._halted_day = today
            self._halted = False

    def is_halted(self, *, today: date, daily_return_pct: Optional[float], target_pct: float = DAILY_TARGET_RETURN_PCT) -> bool:
        self._reset_if_new_day(today)
        if self._halted:
            return True
        if daily_return_pct is None:
            return False
        if float(daily_return_pct) >= float(target_pct):
            self._halted = True
            return True
        return False

    def halt_and_log_once(
        self,
        *,
        today: date,
        strategy: str,
        daily_return_pct: Optional[float],
        target_pct: float = DAILY_TARGET_RETURN_PCT,
        iteration_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> bool:
        """
        If the target is breached, transition to halted and emit the structured log once.

        Returns True if halted (either already halted or newly halted).
        """
        self._reset_if_new_day(today)
        if self._halted:
            return True
        if daily_return_pct is None:
            return False
        if float(daily_return_pct) < float(target_pct):
            return False

        self._halted = True
        try:
            log_json(
                intent_type="strategy.halted.daily_target",
                severity="WARNING",
                strategy=strategy,
                date=str(today),
                daily_return_pct=float(daily_return_pct),
                daily_target_return_pct=float(target_pct),
                iteration_id=iteration_id,
                correlation_id=correlation_id,
                **(extra or {}),
            )
        except Exception:
            pass
        return True

