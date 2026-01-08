"""
Deterministic risk allocation (canonical sizing).

This module centralizes *risk sizing* into a single pure function:
    allocate_risk(strategy_id, signal_confidence, market_state)

Design goals (per risk engineering requirements):
- Same inputs -> same outputs (pure function)
- No randomness
- No hidden globals (no env reads, no module-level mutable state)
- Only constrains and formalizes risk (no "profit optimization" logic)

Terminology
-----------
We use "risk" here as *deployable notional budget* (USD) for a single trade/signal.
Upstream strategy code may request a size/notional. The allocator enforces:
- portfolio/day cap: sum(allocated) <= daily_risk_cap_usd
- per-strategy cap: allocated <= max_strategy_allocation_pct * daily_risk_cap_usd

`market_state` contract
----------------------
This function intentionally accepts a dict-like object to avoid coupling to
any particular service (FastAPI, Cloud Functions, batch backtests, etc.).

Expected keys (all optional unless otherwise noted):
- **buying_power_usd** (float): Used only for fallback cap calculation if a USD cap
  is not provided. Not required if daily_risk_cap_usd is provided.
- **daily_risk_cap_usd** (float): Total risk budget for the day (USD).
- **daily_risk_cap_pct** (float): Alternative to daily_risk_cap_usd, interpreted as
  a fraction of buying_power_usd (0..1). Only used if daily_risk_cap_usd missing.
- **max_strategy_allocation_pct** (float): Max fraction (0..1) of daily cap a single
  strategy may consume.
- **current_allocations_usd** (dict[str, float]): Already-allocated amounts (USD)
  for the day across strategies (excluding the current request).
- **requested_notional_usd** (float): The upstream requested size (USD). If absent,
  requested_allocation_pct may be used.
- **requested_allocation_pct** (float): Alternative requested size as a fraction of
  daily cap (0..1). Only used if requested_notional_usd missing.
- **confidence_scaling** (bool): If True, scales the requested size by
  clamp(signal_confidence, 0..1). Default False to preserve upstream behavior.

Return value
------------
Returns a single float: allocated_notional_usd (>= 0).
"""

from __future__ import annotations

from typing import Any, Mapping


def _as_float(value: Any, *, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    if isinstance(value, bool):
        # Avoid treating booleans as numbers.
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return float(default)
        return float(s)
    return float(default)


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def allocate_risk(strategy_id: str, signal_confidence: float, market_state: Mapping[str, Any]) -> float:
    """
    Allocate deterministic notional (USD) for a strategy signal.
    """
    sid = str(strategy_id or "").strip()
    if not sid:
        raise ValueError("strategy_id must be non-empty")

    conf = _clamp(_as_float(signal_confidence, default=0.0), 0.0, 1.0)

    # --- Resolve daily cap (USD) ---
    daily_cap_usd = _as_float(market_state.get("daily_risk_cap_usd"), default=0.0)
    if daily_cap_usd <= 0:
        # Fall back to pct-of-buying-power if provided.
        bp = _as_float(market_state.get("buying_power_usd"), default=0.0)
        cap_pct = _clamp(_as_float(market_state.get("daily_risk_cap_pct"), default=1.0), 0.0, 1.0)
        daily_cap_usd = max(0.0, bp * cap_pct)

    # If we still can't establish a cap, fail-closed: allocate nothing.
    if daily_cap_usd <= 0:
        return 0.0

    # --- Resolve requested notional (USD) ---
    requested_usd = _as_float(market_state.get("requested_notional_usd"), default=0.0)
    if requested_usd <= 0:
        req_pct = _clamp(_as_float(market_state.get("requested_allocation_pct"), default=0.0), 0.0, 1.0)
        requested_usd = daily_cap_usd * req_pct

    requested_usd = max(0.0, requested_usd)

    # Optional confidence scaling: off by default to preserve existing strategy sizing.
    confidence_scaling = bool(market_state.get("confidence_scaling") is True)
    desired_usd = requested_usd * conf if confidence_scaling else requested_usd

    # --- Apply per-strategy cap ---
    max_pct = _clamp(_as_float(market_state.get("max_strategy_allocation_pct"), default=1.0), 0.0, 1.0)
    per_strategy_cap_usd = daily_cap_usd * max_pct
    allocated_usd = min(desired_usd, per_strategy_cap_usd)

    # --- Apply daily cap (aggregate) ---
    current_allocs = market_state.get("current_allocations_usd") or {}
    total_other = 0.0
    if isinstance(current_allocs, Mapping):
        for k, v in current_allocs.items():
            # Exclude self if present; allocator should not double-count.
            if str(k) == sid:
                continue
            total_other += max(0.0, _as_float(v, default=0.0))

    remaining = max(0.0, daily_cap_usd - total_other)
    allocated_usd = min(allocated_usd, remaining)

    # --- Safety assertions (post-constraint) ---
    # Small epsilon to tolerate float roundoff.
    eps = 1e-9
    assert allocated_usd + eps >= 0.0
    assert allocated_usd <= per_strategy_cap_usd + eps
    assert total_other + allocated_usd <= daily_cap_usd + eps

    return float(allocated_usd)

