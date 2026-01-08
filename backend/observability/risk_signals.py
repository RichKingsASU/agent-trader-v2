from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from backend.observability.correlation import get_or_create_correlation_id


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except Exception:
        try:
            return float(str(x))
        except Exception:
            return None


def _safe_pct(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    if numer is None or denom is None or denom <= 0:
        return None
    return (numer / denom) * 100.0


@dataclass(frozen=True, slots=True)
class CapitalUtilization:
    equity_usd: Optional[float]
    exposure_usd: Optional[float]
    capital_utilization_pct: Optional[float]


def compute_capital_utilization(account_snapshot: dict[str, Any]) -> CapitalUtilization:
    """
    Best-effort capital utilization from an account snapshot.

    Expected snapshot shape (best-effort):
    - equity: str|float
    - positions: list[dict] with either:
      - market_value (preferred), or
      - qty + current_price
    """
    equity = _to_float(account_snapshot.get("equity"))
    positions = account_snapshot.get("positions") or []
    exposure = 0.0
    ok = False
    if isinstance(positions, list):
        for p in positions:
            if not isinstance(p, dict):
                continue
            mv = _to_float(p.get("market_value"))
            if mv is None:
                qty = _to_float(p.get("qty"))
                px = _to_float(p.get("current_price"))
                if qty is None or px is None:
                    continue
                mv = qty * px
            exposure += abs(float(mv))
            ok = True
    if not ok:
        return CapitalUtilization(equity_usd=equity, exposure_usd=None, capital_utilization_pct=None)
    return CapitalUtilization(
        equity_usd=equity,
        exposure_usd=exposure,
        capital_utilization_pct=_safe_pct(exposure, equity),
    )


@dataclass(frozen=True, slots=True)
class StrategyRisk:
    risk_per_strategy_usd: Optional[float]
    risk_per_strategy_pct_equity: Optional[float]


def compute_risk_per_strategy(*, proposed_allocation_usd: Any, equity_usd: Optional[float]) -> StrategyRisk:
    alloc = _to_float(proposed_allocation_usd)
    return StrategyRisk(
        risk_per_strategy_usd=alloc,
        risk_per_strategy_pct_equity=_safe_pct(alloc, equity_usd),
    )


@dataclass(frozen=True, slots=True)
class DrawdownVelocity:
    drawdown_pct: Optional[float]
    drawdown_velocity_pct_per_min: Optional[float]


_LAST_DRAWDOWN: dict[str, tuple[float, float]] = {}


def compute_drawdown_velocity(
    *,
    key: str,
    starting_equity_usd: Optional[float],
    current_equity_usd: Optional[float],
) -> DrawdownVelocity:
    """
    Drawdown velocity as delta(drawdown_pct) / delta(minutes) using a process-local cache.

    - drawdown_pct is in [0, 100]
    - velocity is percentage points per minute (pp/min)
    """
    if starting_equity_usd is None or starting_equity_usd <= 0 or current_equity_usd is None:
        return DrawdownVelocity(drawdown_pct=None, drawdown_velocity_pct_per_min=None)

    drawdown_pct = max(0.0, ((starting_equity_usd - current_equity_usd) / starting_equity_usd) * 100.0)
    now_s = time.time()

    prev = _LAST_DRAWDOWN.get(key)
    _LAST_DRAWDOWN[key] = (now_s, drawdown_pct)
    if not prev:
        return DrawdownVelocity(drawdown_pct=drawdown_pct, drawdown_velocity_pct_per_min=None)

    prev_s, prev_dd = prev
    dt_min = max(0.0, (now_s - prev_s) / 60.0)
    if dt_min <= 0:
        return DrawdownVelocity(drawdown_pct=drawdown_pct, drawdown_velocity_pct_per_min=None)

    vel = (drawdown_pct - prev_dd) / dt_min
    return DrawdownVelocity(drawdown_pct=drawdown_pct, drawdown_velocity_pct_per_min=vel)


def risk_correlation_id(
    *,
    correlation_id: str | None = None,
    headers: Optional[dict[str, Any]] = None,
) -> str:
    """
    Correlation ID policy:
    - Use explicit correlation_id when provided (signal/allocation/execution chain)
    - Else fall back to any ambient/request context (best-effort)
    - Else generate
    """
    return get_or_create_correlation_id(headers=headers, correlation_id=correlation_id)

