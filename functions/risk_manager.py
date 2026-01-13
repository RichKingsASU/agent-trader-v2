"""
Risk manager kill-switch checks used by the unit tests.

This module is intentionally lightweight: production code may wire these checks
to Firestore, but tests patch `_get_high_water_mark` so the default implementation
can be a safe stub.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Test expectations:
# - HWM drawdown threshold: 10% (90% of HWM passes, 85% fails)
# - Trade size limit: 5% of buying power
DEFAULT_MAX_DRAWDOWN_PCT = 10.0
DEFAULT_MAX_TRADE_PCT_OF_BP = 0.05


def _as_float(v: Any) -> float:
    """Convert number-like values to float; None/empty-string -> 0.0."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        return 0.0 if s == "" else float(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    equity: float
    buying_power: float
    cash: float


@dataclass(frozen=True, slots=True)
class TradeRequest:
    symbol: str
    side: str  # "buy" | "sell"
    qty: float
    notional_usd: float


@dataclass(frozen=True, slots=True)
class RiskCheckResult:
    allowed: bool
    reason: Optional[str] = None


def _get_high_water_mark() -> Optional[float]:
    """
    Fetch the current High Water Mark (HWM) equity.

    In production this should be backed by Firestore; for tests this function is patched.
    """
    return None


def _check_high_water_mark(*, current_equity: float, high_water_mark: Optional[float]) -> Optional[str]:
    """
    Reject trades if current equity drawdown exceeds DEFAULT_MAX_DRAWDOWN_PCT.
    Returns an error string (contains 'KILL-SWITCH') or None if check passes.
    """
    if high_water_mark is None:
        logger.warning("High Water Mark not set; skipping drawdown check.")
        return None

    hwm = float(high_water_mark)
    if hwm <= 0:
        return None

    eq = float(current_equity)
    drawdown_pct = ((hwm - eq) / hwm) * 100.0
    if drawdown_pct <= DEFAULT_MAX_DRAWDOWN_PCT:
        return None

    return (
        "KILL-SWITCH: High Water Mark drawdown exceeded "
        f"({drawdown_pct:.2f}% > {DEFAULT_MAX_DRAWDOWN_PCT:.2f}%). "
        f"equity={eq:,.0f}, high_water_mark={hwm:,.0f}"
    )


def _check_trade_size(*, trade_notional: float, buying_power: float) -> Optional[str]:
    """
    Reject trades whose notional exceeds DEFAULT_MAX_TRADE_PCT_OF_BP of buying power.
    Returns an error string (contains 'KILL-SWITCH') or None if check passes.
    """
    bp = float(buying_power)
    if bp <= 0:
        return f"KILL-SWITCH: Buying power is {bp:,.0f}; trade blocked."

    notional = float(trade_notional)
    max_allowed = bp * DEFAULT_MAX_TRADE_PCT_OF_BP
    if notional <= max_allowed:
        return None

    pct = (notional / bp) * 100.0
    return (
        "KILL-SWITCH: Trade size exceeds limit "
        f"({notional:,.0f} = {pct:.2f}% of buying power; max {max_allowed:,.0f})."
    )


def validate_trade_risk(account: AccountSnapshot, trade: TradeRequest) -> RiskCheckResult:
    """
    Validate a proposed trade against risk checks. The order of checks matches tests:
    1) account snapshot sanity
    2) HWM drawdown kill-switch
    3) trade size kill-switch
    """
    equity = _as_float(account.equity)
    buying_power = _as_float(account.buying_power)
    cash = _as_float(account.cash)

    if equity < 0:
        return RiskCheckResult(False, "Invalid account snapshot: equity is negative")
    if buying_power < 0:
        return RiskCheckResult(False, "Invalid account snapshot: buying_power is negative")
    if cash < 0:
        return RiskCheckResult(False, "Invalid account snapshot: cash is negative")

    notional = _as_float(trade.notional_usd)
    if notional < 0:
        return RiskCheckResult(False, "Invalid trade request: notional_usd is negative")

    hwm = _get_high_water_mark()
    err = _check_high_water_mark(current_equity=equity, high_water_mark=hwm)
    if err:
        return RiskCheckResult(False, err)

    err = _check_trade_size(trade_notional=notional, buying_power=buying_power)
    if err:
        return RiskCheckResult(False, err)

    return RiskCheckResult(True, None)


__all__ = [
    "AccountSnapshot",
    "TradeRequest",
    "RiskCheckResult",
    "validate_trade_risk",
    "_as_float",
    "_get_high_water_mark",
    "_check_high_water_mark",
    "_check_trade_size",
]

