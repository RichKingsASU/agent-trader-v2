"""
Risk Manager (Kill-Switch) — unit-testable core.

This module intentionally keeps logic lightweight and deterministic:
- No live execution enablement
- Pure calculations + best-effort Firestore read hook (_get_high_water_mark)

It is used by unit tests in `tests/test_risk_manager.py`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Policy thresholds (aligned with tests)
MAX_DRAWDOWN_PCT = 10.0  # 10% max drawdown from HWM before kill-switch
MAX_TRADE_PCT_OF_BUYING_POWER = 5.0  # 5% max trade notional vs buying power


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    buying_power: float
    cash: float


@dataclass(frozen=True)
class TradeRequest:
    symbol: str
    side: str  # "buy" / "sell" (treated equivalently for risk sizing)
    qty: float
    notional_usd: float


@dataclass(frozen=True)
class RiskCheckResult:
    allowed: bool
    reason: Optional[str] = None


def _as_float(v: Any) -> float:
    """Convert value to float with safe handling for None/empty strings."""
    if v is None:
        return 0.0
    if isinstance(v, float):
        return v
    if isinstance(v, int):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        return float(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def _fmt_int(n: float) -> str:
    """Format as an integer with commas (e.g. 100000 -> '100,000')."""
    return f"{int(round(n)):,}"


def _get_high_water_mark() -> Optional[float]:
    """
    Best-effort hook for production integration.

    In unit tests this function is patched. In production, this may be implemented
    to read HWM from a datastore (e.g., Firestore).
    """
    return None


def _check_high_water_mark(*, current_equity: Any, high_water_mark: Any) -> Optional[str]:
    """
    Kill-switch drawdown check.

    Returns:
      - None if allowed
      - string reason if blocked
    """
    current = _as_float(current_equity)

    if high_water_mark is None:
        logger.warning("High Water Mark not set; skipping drawdown check.")
        return None

    hwm = _as_float(high_water_mark)
    if hwm <= 0:
        return None

    drawdown_pct = ((hwm - current) / hwm) * 100.0
    if drawdown_pct <= MAX_DRAWDOWN_PCT:
        return None

    return (
        "KILL-SWITCH: High Water Mark drawdown exceeded. "
        f"Current equity {_fmt_int(current)} is {drawdown_pct:.2f}% below "
        f"High Water Mark {_fmt_int(hwm)} (max allowed: {MAX_DRAWDOWN_PCT:.2f}%)."
    )


def _check_trade_size(*, trade_notional: Any, buying_power: Any) -> Optional[str]:
    """
    Kill-switch trade sizing check: notional must be <= 5% of buying power.
    """
    notional = _as_float(trade_notional)
    bp = _as_float(buying_power)

    if bp <= 0:
        return f"KILL-SWITCH: Buying power is {_fmt_int(bp)}. Cannot validate trade size."

    max_allowed = (MAX_TRADE_PCT_OF_BUYING_POWER / 100.0) * bp
    if notional <= max_allowed:
        return None

    pct = (notional / bp) * 100.0
    return (
        "KILL-SWITCH: Trade size exceeds limit. "
        f"Trade {_fmt_int(notional)} is {pct:.2f}% of buying power {_fmt_int(bp)}; "
        f"max allowed is {_fmt_int(max_allowed)} ({MAX_TRADE_PCT_OF_BUYING_POWER:.2f}%)."
    )


def validate_trade_risk(account_snapshot: AccountSnapshot, trade_request: TradeRequest) -> RiskCheckResult:
    """
    Validate a proposed trade against kill-switch rules.

    Fail-closed on invalid inputs.
    """
    equity = _as_float(account_snapshot.equity)
    bp = _as_float(account_snapshot.buying_power)
    cash = _as_float(account_snapshot.cash)
    notional = _as_float(trade_request.notional_usd)

    if equity < 0:
        return RiskCheckResult(False, f"Invalid account snapshot: equity is negative ({account_snapshot.equity})")
    if bp < 0:
        return RiskCheckResult(False, f"Invalid account snapshot: buying_power is negative ({account_snapshot.buying_power})")
    if cash < 0:
        return RiskCheckResult(False, f"Invalid account snapshot: cash is negative ({account_snapshot.cash})")
    if notional < 0:
        return RiskCheckResult(False, f"Invalid trade request: notional_usd is negative ({trade_request.notional_usd})")

    hwm = _get_high_water_mark()
    hwm_err = _check_high_water_mark(current_equity=equity, high_water_mark=hwm)
    if hwm_err:
        return RiskCheckResult(False, hwm_err)

    size_err = _check_trade_size(trade_notional=notional, buying_power=bp)
    if size_err:
        return RiskCheckResult(False, size_err)

    return RiskCheckResult(True, None)

