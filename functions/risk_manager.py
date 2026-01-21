"""
Risk manager kill-switch logic.

This module provides dependency-light safety checks to validate trade requests
before execution. The core contract (as documented in `functions/RISK_MANAGER_*`)
is:

- Reject trades if current equity is more than 10% below the High Water Mark (HWM)
- Reject trades if trade notional exceeds 5% of buying power

Thresholds are sourced from environment variables in production (when set),
otherwise defaults are used. Values are NOT hardcoded inline; they are resolved
once and passed explicitly to checks to avoid implicit globals.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:  # Optional dependency; unit tests should run without cloud libs.
    from google.cloud import firestore  # type: ignore
except Exception:  # pragma: no cover
    firestore = None  # type: ignore


# -----------------------------
# Threshold defaults (documented behavior)
# -----------------------------

# Default max drawdown, expressed as a percentage (10.0 == 10%).
DEFAULT_MAX_DRAWDOWN_PCT = Decimal("10.0")
# Default max trade size, expressed as a percentage of buying power (5.0 == 5%).
DEFAULT_MAX_TRADE_BP_PCT = Decimal("5.0")


def _env_decimal(name: str) -> Optional[Decimal]:
    v = os.getenv(name)
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    return Decimal(s)


def _resolve_max_drawdown_pct(drawdown_threshold: Decimal | None = None) -> Decimal:
    """
    Resolve the max drawdown percent from:
    - explicit argument (highest priority)
    - environment `RISK_MAX_DRAWDOWN_PCT`
    - module default `DEFAULT_MAX_DRAWDOWN_PCT`
    """
    if drawdown_threshold is not None:
        return Decimal(str(drawdown_threshold))
    return _env_decimal("RISK_MAX_DRAWDOWN_PCT") or DEFAULT_MAX_DRAWDOWN_PCT


def _resolve_max_trade_bp_pct(max_trade_bp_pct: Decimal | None = None) -> Decimal:
    """
    Resolve the max trade size percent of buying power from:
    - explicit argument (highest priority)
    - environment `RISK_MAX_TRADE_BP_PCT`
    - module default `DEFAULT_MAX_TRADE_BP_PCT`
    """
    if max_trade_bp_pct is not None:
        return Decimal(str(max_trade_bp_pct))
    return _env_decimal("RISK_MAX_TRADE_BP_PCT") or DEFAULT_MAX_TRADE_BP_PCT


# -----------------------------
# Data contracts
# -----------------------------


@dataclass(frozen=True)
class AccountSnapshot:
    # Keep fields flexible; tests pass ints and production may pass strings/floats.
    equity: Any
    buying_power: Any
    cash: Any


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


def _as_decimal(v: Any) -> Decimal:
    """
    Convert various types to Decimal safely for precision.
    
    Handles None, numeric types, and string representations.
    Returns Decimal("0") for None or empty strings.
    """
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
        return Decimal(s)
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


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
        except ValueError:
            raise TypeError(f"Could not convert string to float: {v!r}")
    raise TypeError(f"Expected number-like value, got {type(v).__name__}")


def calculate_drawdown(current: Any, hwm: Any) -> Decimal:
    """
    Calculate drawdown percentage from High Water Mark.
    
    Args:
        current: Current equity value (as string for precision)
        hwm: High Water Mark value (as string for precision)
    
    Returns:
        Drawdown as a Decimal percentage (e.g., Decimal("5.25") for 5.25%)
    
    Example:
        >>> calculate_drawdown("95000", "100000")
        Decimal('5.00')
    """
    current_dec = _as_decimal(current)
    hwm_dec = _as_decimal(hwm)
    
    if hwm_dec <= 0:
        return Decimal("0")
    
    drawdown_pct = ((hwm_dec - current_dec) / hwm_dec) * Decimal("100")
    return drawdown_pct.quantize(Decimal("0.01"))  # percent, 2dp


def _get_high_water_mark(db: Any | None = None) -> Optional[Any]:
    """
    Retrieve the High Water Mark from Firestore if available.

    The documented location for this module is:
    `riskManagement/highWaterMark` with field `value`.

    In unit tests, this function is typically patched.
    """
    if db is None or firestore is None:
        return None
    try:
        doc = db.collection("riskManagement").document("highWaterMark").get()
        if not getattr(doc, "exists", False):
            return None
        data = doc.to_dict() or {}
        return data.get("value")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to read HWM from Firestore: %s", e)
        return None


def _check_high_water_mark(
    current_equity: Any,
    high_water_mark: Optional[Any],
    *,
    max_drawdown_pct: Decimal
) -> Optional[str]:
    """
    Check if current equity is more than `max_drawdown_pct` below High Water Mark.

    Returns an error string containing "KILL-SWITCH" on breach; otherwise None.
    """
    if high_water_mark is None:
        logger.warning("High Water Mark not set; skipping drawdown check")
        return None

    current_dec = _as_decimal(current_equity)
    hwm_dec = _as_decimal(high_water_mark)

    if hwm_dec <= 0:
        logger.warning("High Water Mark is <= 0 (%s); skipping drawdown check", high_water_mark)
        return None

    drawdown_pct = calculate_drawdown(current_dec, hwm_dec)

    # At exactly the threshold, allow. Breach only if strictly greater.
    if drawdown_pct > max_drawdown_pct:
        threshold_equity = (hwm_dec * (Decimal("100") - max_drawdown_pct) / Decimal("100")).quantize(Decimal("0.01"))
        return (
            "KILL-SWITCH: "
            f"Current equity ${current_dec:,.2f} is {drawdown_pct:,.2f}% below High Water Mark ${hwm_dec:,.2f} "
            f"(threshold: ${threshold_equity:,.2f}, max allowed drawdown: {max_drawdown_pct}% )"
        )

    return None


def _check_trade_size(
    trade_notional: float,
    buying_power: Any,
    *,
    max_trade_bp_pct: Decimal
) -> Optional[str]:
    """
    Reject if trade notional exceeds `max_trade_bp_pct` of buying power.
    """
    bp_dec = _as_decimal(buying_power)
    trade_dec = _as_decimal(trade_notional)
    
    if bp_dec <= 0:
        return (
            f"KILL-SWITCH: Buying power is {bp_dec}. "
            "Cannot validate trade size."
        )
    
    max_allowed = (bp_dec * max_trade_bp_pct / Decimal("100")).quantize(Decimal("0.01"))
    
    if trade_dec > max_allowed:
        size_pct = ((trade_dec / bp_dec) * Decimal("100")).quantize(Decimal("0.01"))
        return (
            "KILL-SWITCH: "
            f"Trade size {trade_dec:,.2f} ({size_pct:,.2f}% of buying power) exceeds maximum allowed {max_allowed:,.2f} "
            f"({max_trade_bp_pct}% of buying power {bp_dec:,.2f})"
        )
    
    return None


def validate_trade_risk(
    account_snapshot: AccountSnapshot,
    trade_request: TradeRequest,
    db: Any | None = None
) -> RiskCheckResult:
    """
    This is a pure utility function that checks:
    1. Current equity is NOT more than 5% below the High Water Mark
    2. Trade size does NOT exceed 5% of buying power
    
    Args:
        account_snapshot: Current account state (equity, buying_power, cash as strings)
        trade_request: Proposed trade details (symbol, side, qty, notional_usd)
        db: Optional Firestore client (will create if not provided)
    
    Returns:
        RiskCheckResult with allowed=True if all checks pass,
        or allowed=False with reason if any check fails
    
    Example:
        >>> account = AccountSnapshot(equity="100000", buying_power="50000", cash="25000")
        >>> trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=2000)
        >>> result = validate_trade_risk(account, trade)
        >>> if not result.allowed:
        ...     print(f"Trade rejected: {result.reason}")
    """
    # Resolve thresholds once; pass explicitly to avoid implicit globals.
    max_drawdown_pct = _resolve_max_drawdown_pct()
    max_trade_bp_pct = _resolve_max_trade_bp_pct()

    # Validate inputs using Decimal
    equity_dec = _as_decimal(account_snapshot.equity)
    bp_dec = _as_decimal(account_snapshot.buying_power)
    
    if equity_dec < 0:
        return RiskCheckResult(
            allowed=False,
            reason=f"Invalid account snapshot: equity is negative ({account_snapshot.equity})"
        )
    
    if bp_dec < 0:
        return RiskCheckResult(
            allowed=False,
            reason=f"Invalid account snapshot: buying_power is negative ({account_snapshot.buying_power})"
        )
    
    if trade_request.notional_usd < 0:
        return RiskCheckResult(
            allowed=False,
            reason=f"Invalid trade request: notional_usd is negative ({trade_request.notional_usd})"
        )
    
    # Check 1: High Water Mark drawdown check
    high_water_mark = _get_high_water_mark(db=db)
    hwm_error = _check_high_water_mark(account_snapshot.equity, high_water_mark, max_drawdown_pct=max_drawdown_pct)
    if hwm_error:
        logger.error("Trade rejected: %s", hwm_error)
        return RiskCheckResult(allowed=False, reason=hwm_error)
    
    # Check 2: Trade size as percentage of buying power
    trade_size_error = _check_trade_size(
        trade_request.notional_usd,
        account_snapshot.buying_power,
        max_trade_bp_pct=max_trade_bp_pct,
    )
    if trade_size_error:
        logger.error("Trade rejected: %s", trade_size_error)
        return RiskCheckResult(allowed=False, reason=trade_size_error)
    
    # All checks passed
    notional_dec = Decimal(str(trade_request.notional_usd))
    pct_bp = (notional_dec / bp_dec * Decimal("100")) if bp_dec > 0 else Decimal("0")
    
    logger.info(
        "Trade validation passed: %s %s %.0f shares, notional=%s (%s%% of buying power)",
        trade_request.side.upper(),
        trade_request.symbol,
        trade_request.qty,
        notional_dec,
        pct_bp.quantize(Decimal("0.01"))
    )
    
    return RiskCheckResult(allowed=True, reason=None)
