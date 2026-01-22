"""
Risk Manager: drawdown + trade-size kill-switch checks.

SAFE CLEANUP NOTE:
- This module is used by unit tests and must remain importable in minimal CI.
- Firestore access is optional and must be lazy.
- No broker/execution actions are performed here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Defaults (kept intentionally simple; callers may override via function params).
DEFAULT_DRAWDOWN_THRESHOLD = Decimal("0.10")  # 10% max drawdown from HWM
DEFAULT_MAX_TRADE_PCT_BP = Decimal("0.05")  # 5% max trade size vs buying power


@dataclass(frozen=True)
class AccountSnapshot:
    equity: float
    buying_power: float
    cash: float


@dataclass(frozen=True)
class TradeRequest:
    symbol: str
    side: str  # "buy" or "sell"
    qty: float
    notional_usd: float


@dataclass(frozen=True)
class RiskCheckResult:
    allowed: bool
    reason: Optional[str] = None


def _as_float(v: Any) -> float:
    """
    Safely convert value to float.
    Returns 0.0 for None or empty strings.
    """
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError as e:
            raise TypeError(f"Could not convert string to float: {v!r}") from e
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def _as_decimal(v: Any) -> Decimal:
    if v is None:
        return Decimal("0")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return Decimal("0")
        try:
            return Decimal(s)
        except InvalidOperation as e:
            raise TypeError(f"Could not convert string to Decimal: {v!r}") from e
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def _fmt_money(v: Any) -> str:
    # Tests expect comma-separated integers (e.g., "85,000").
    try:
        return f"{int(_as_decimal(v)):,.0f}"
    except Exception:
        return str(v)


def _get_high_water_mark(db: Any | None = None) -> Optional[float]:
    """
    Best-effort read of High Water Mark from Firestore.

    This is optional: tests patch this function, and CI may not have cloud libs.
    Returns:
        High water mark as float, or None if unavailable.
    """
    if db is None:
        return None
    try:
        doc = db.collection("systemStatus").document("risk").get()
        if not getattr(doc, "exists", False):
            return None
        data = doc.to_dict() or {}
        hwm = data.get("high_water_mark")
        if hwm is None:
            return None
        return float(_as_decimal(hwm))
    except Exception:
        # Keep failure isolated; risk checks should remain usable without Firestore.
        return None


def _check_high_water_mark(
    current_equity: Any,
    high_water_mark: Any,
    *,
    drawdown_threshold: Decimal = DEFAULT_DRAWDOWN_THRESHOLD,
) -> Optional[str]:
    """
    Reject trading if drawdown from High Water Mark exceeds `drawdown_threshold`.

    Returns:
        None if ok, otherwise a KILL-SWITCH reason string.
    """
    if high_water_mark is None:
        # No HWM configured => cannot enforce drawdown; pass with warning.
        logger.warning("High Water Mark not set; skipping drawdown enforcement")
        return None

    hwm = _as_decimal(high_water_mark)
    if hwm <= 0:
        return None

    cur = _as_decimal(current_equity)
    # Drawdown as a fraction in [0,1].
    drawdown = (hwm - cur) / hwm
    if drawdown <= drawdown_threshold:
        return None

    drawdown_pct = (drawdown * Decimal("100")).quantize(Decimal("0.01"))
    thresh_pct = (drawdown_threshold * Decimal("100")).quantize(Decimal("0.01"))
    return (
        "KILL-SWITCH: High Water Mark drawdown "
        f"{drawdown_pct}% exceeds threshold {thresh_pct}%. "
        f"Current equity {_fmt_money(cur)} is {drawdown_pct}% below High Water Mark {_fmt_money(hwm)}."
    )


def _check_trade_size(
    trade_notional: Any,
    buying_power: Any,
    *,
    max_trade_pct_bp: Decimal = DEFAULT_MAX_TRADE_PCT_BP,
) -> Optional[str]:
    """
    Reject trades larger than `max_trade_pct_bp` of buying power.
    """
    bp = _as_decimal(buying_power)
    if bp <= 0:
        return f"KILL-SWITCH: Buying power is {bp}. Cannot validate trade size."

    trade = _as_decimal(trade_notional)
    max_allowed = (bp * max_trade_pct_bp).quantize(Decimal("0.01"))
    if trade <= max_allowed:
        return None

    pct = ((trade / bp) * Decimal("100")).quantize(Decimal("0.01"))
    pct_limit = (max_trade_pct_bp * Decimal("100")).quantize(Decimal("0.01"))
    return (
        "KILL-SWITCH: Trade size "
        f"{_fmt_money(trade)} ({pct}% of buying power) exceeds maximum allowed "
        f"{_fmt_money(max_allowed)} ({pct_limit}% of buying power {_fmt_money(bp)})"
    )


def validate_trade_risk(
    account_snapshot: AccountSnapshot,
    trade_request: TradeRequest,
    db: Any | None = None,
    *,
    drawdown_threshold: Decimal = DEFAULT_DRAWDOWN_THRESHOLD,
    max_trade_pct_bp: Decimal = DEFAULT_MAX_TRADE_PCT_BP,
) -> RiskCheckResult:
    """
    Validate a proposed trade against drawdown and trade-size caps.
    """
    equity = _as_decimal(account_snapshot.equity)
    buying_power = _as_decimal(account_snapshot.buying_power)

    if equity < 0:
        return RiskCheckResult(allowed=False, reason=f"Invalid account snapshot: equity is negative ({account_snapshot.equity})")
    if buying_power < 0:
        return RiskCheckResult(
            allowed=False,
            reason=f"Invalid account snapshot: buying_power is negative ({account_snapshot.buying_power})",
        )
    if _as_decimal(trade_request.notional_usd) < 0:
        return RiskCheckResult(
            allowed=False,
            reason=f"Invalid trade request: notional_usd is negative ({trade_request.notional_usd})",
        )

    hwm = _get_high_water_mark(db=db)
    hwm_error = _check_high_water_mark(
        current_equity=equity,
        high_water_mark=hwm,
        drawdown_threshold=drawdown_threshold,
    )
    if hwm_error:
        return RiskCheckResult(allowed=False, reason=hwm_error)

    size_error = _check_trade_size(
        trade_notional=trade_request.notional_usd,
        buying_power=buying_power,
        max_trade_pct_bp=max_trade_pct_bp,
    )
    if size_error:
        return RiskCheckResult(allowed=False, reason=size_error)

    return RiskCheckResult(allowed=True, reason=None)

