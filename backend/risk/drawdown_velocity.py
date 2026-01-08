from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class EquityPoint:
    ts: datetime
    equity: float


@dataclass(frozen=True, slots=True)
class DrawdownVelocity:
    """
    Rolling drawdown velocity metrics.

    Conventions:
    - drawdown_pct: (HWM - equity) / HWM * 100, in percent points
    - velocity_pct_per_min: positive means drawdown is increasing (loss accelerating)
    """

    window_seconds: int
    points_used: int
    hwm_equity: float
    current_equity: float
    current_drawdown_pct: float
    velocity_pct_per_min: float
    window_start: datetime
    window_end: datetime


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_drawdown_velocity(
    points: Sequence[EquityPoint] | Iterable[EquityPoint],
    *,
    window_seconds: int,
    now: datetime | None = None,
    min_points: int = 3,
) -> DrawdownVelocity | None:
    """
    Compute rolling drawdown velocity from an equity time-series.

    We deliberately use a conservative, noise-resistant definition:
    - Use a fixed lookback window [now-window, now]
    - Define HWM within the window
    - Compute drawdown at window start and at window end relative to that HWM
    - Velocity = max(0, dd_end - dd_start) / dt_minutes

    Returns None when insufficient data is available.
    """
    if window_seconds <= 0:
        raise ValueError("window_seconds must be > 0")
    if min_points < 2:
        raise ValueError("min_points must be >= 2")

    now_utc = _as_utc(now or datetime.now(timezone.utc))
    start_cutoff = now_utc.timestamp() - float(window_seconds)

    # Normalize, filter, sort.
    normalized: list[EquityPoint] = []
    for p in points:
        ts = _as_utc(p.ts)
        if ts.timestamp() < start_cutoff:
            continue
        if p.equity is None:
            continue
        try:
            eq = float(p.equity)
        except Exception:
            continue
        if eq <= 0:
            continue
        normalized.append(EquityPoint(ts=ts, equity=eq))

    if len(normalized) < min_points:
        return None

    normalized.sort(key=lambda x: x.ts)
    window_start = normalized[0].ts
    window_end = normalized[-1].ts

    # If timestamps collapse, we cannot compute a rate.
    dt_s = (window_end - window_start).total_seconds()
    if dt_s <= 0:
        return None

    hwm = max(p.equity for p in normalized)
    if hwm <= 0:
        return None

    equity_start = normalized[0].equity
    equity_end = normalized[-1].equity

    dd_start = max(0.0, (hwm - equity_start) / hwm * 100.0)
    dd_end = max(0.0, (hwm - equity_end) / hwm * 100.0)

    dt_min = dt_s / 60.0
    velocity = max(0.0, dd_end - dd_start) / dt_min if dt_min > 0 else 0.0

    return DrawdownVelocity(
        window_seconds=int(window_seconds),
        points_used=len(normalized),
        hwm_equity=float(hwm),
        current_equity=float(equity_end),
        current_drawdown_pct=float(dd_end),
        velocity_pct_per_min=float(velocity),
        window_start=window_start,
        window_end=window_end,
    )

