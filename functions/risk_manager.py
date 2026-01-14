"""
Risk Management Module: High Water Mark (HWM) and Drawdown Tracking

Provides safety checks to prevent trades under dangerous market or account conditions.
Uses Decimal for all monetary calculations to maintain precision.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from google.cloud import firestore

logger = logging.getLogger(__name__)

# Risk thresholds (configurable via environment in production)
DEFAULT_DRAWDOWN_THRESHOLD = Decimal("0.05")  # 5% drawdown threshold
MIN_EQUITY_FOR_TRACKING = Decimal("100.0")  # Minimum equity to start tracking


@dataclass(frozen=True)
class AccountSnapshot:
    """
    Attributes:
        equity: Current account equity (total value) - stored as string for precision
        buying_power: Available buying power - stored as string for precision
        cash: Available cash - stored as string for precision
    """
    equity: str
    buying_power: str
    cash: str


@dataclass
class RiskCheckResult:
    """
    Result of risk validation checks.
    
    Attributes:
        allowed: Whether the trade is allowed
        reason: Explanation if trade is rejected (None if allowed)
    """
    allowed: bool
    reason: Optional[str] = None


@dataclass(frozen=True)
class TradeRequest:
    symbol: str
    side: str # "buy" or "sell"
    qty: float
    notional_usd: float


def _get_firestore() -> firestore.Client:
    """Get or initialize Firestore client."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return firestore.client()


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


def calculate_drawdown(current: str, hwm: str) -> Decimal:
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
    
    drawdown = ((hwm_dec - current_dec) / hwm_dec) * Decimal("100")
    return drawdown.quantize(Decimal("0.01"))  # Round to 2 decimal places


def _get_high_water_mark(db: Optional[firestore.Client] = None) -> Optional[str]:
    """
    Calculate current drawdown percentage and determine if threshold is breached.
    
    The HWM is stored at: systemStatus/risk
    
    Args:
        current_equity: Current account equity
        high_water_mark: Highest equity ever recorded
    
    Returns:
        High water mark value as string or None if not found
    """
    if high_water_mark <= 0:
        logger.warning("High water mark is zero or negative, cannot calculate drawdown")
        return Decimal("0"), False
    
    try:
        doc = client.collection("systemStatus").document("risk").get()
        if not doc.exists:
            logger.warning("Risk document not found at systemStatus/risk")
            return None
        
        data = doc.to_dict() or {}
        hwm = data.get("high_water_mark")
        
        if hwm is None:
            logger.warning("High Water Mark field is missing")
            return None
        
        return str(hwm)
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to retrieve High Water Mark from Firestore: %s", e)
        return None


def update_high_water_mark(current_equity: str, db: Optional[firestore.Client] = None) -> bool:
    """
    Update the High Water Mark in Firestore if current equity is higher.
    
    The HWM is stored at: systemStatus/risk
    
    Args:
        current_equity: Current equity value as string
        db: Firestore client (optional, will create if not provided)
    
    Returns:
        True if HWM was updated, False otherwise
    """
    client = db or _get_firestore()
    
    try:
        current_dec = _as_decimal(current_equity)
        doc_ref = client.collection("systemStatus").document("risk")
        doc = doc_ref.get()
        
        if not doc.exists:
            # Initialize the document with current equity as HWM
            doc_ref.set({
                "high_water_mark": current_equity,
                "last_updated": firestore.SERVER_TIMESTAMP
            })
            logger.info(f"Initialized High Water Mark: {current_equity}")
            return True
        
        data = doc.to_dict() or {}
        existing_hwm = data.get("high_water_mark")
        
        if existing_hwm is None:
            # Set HWM if it doesn't exist
            doc_ref.update({
                "high_water_mark": current_equity,
                "last_updated": firestore.SERVER_TIMESTAMP
            })
            logger.info(f"Set High Water Mark: {current_equity}")
            return True
        
        existing_dec = _as_decimal(existing_hwm)
        
        if current_dec > existing_dec:
            # Update HWM to new high
            doc_ref.update({
                "high_water_mark": current_equity,
                "last_updated": firestore.SERVER_TIMESTAMP
            })
            logger.info(f"Updated High Water Mark: {existing_hwm} -> {current_equity}")
            return True
        
        return False
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to update High Water Mark in Firestore: %s", e)
        return False


def _check_high_water_mark(
    current_equity: str,
    high_water_mark: Optional[str]
) -> Optional[str]:
    """
    Check if current equity is more than 5% below the High Water Mark.
    
    Args:
        current_equity: Current account equity (as string)
        high_water_mark: High water mark value (or None if not set)
    
    Returns:
        Error message if check fails, None if passes (returns "HALT" for drawdown breach)
    """
    threshold = drawdown_threshold or DEFAULT_DRAWDOWN_THRESHOLD
    
    # Convert current equity to Decimal for precision
    try:
        current_equity = _safe_decimal(current_equity_str, "current_equity")
    except ValueError as e:
        logger.error(f"Invalid current_equity value: {e}")
        raise
    
    # Don't track accounts with very low equity
    if current_equity < MIN_EQUITY_FOR_TRACKING:
        logger.warning(
            "High Water Mark not set. Cannot validate equity drawdown. "
            "Consider setting HWM at systemStatus/risk"
        )
        return {
            "high_water_mark": current_equity,
            "current_equity": current_equity,
            "drawdown_percent": Decimal("0"),
            "trading_enabled": False,
            "hwm_updated": False,
            "reason": "Equity below minimum threshold",
        }
    
    hwm_dec = _as_decimal(high_water_mark)
    
    if hwm_dec <= 0:
        logger.warning("High Water Mark is <= 0 (%s), skipping drawdown check", high_water_mark)
        return None
    
    # Calculate drawdown percentage
    drawdown_pct = calculate_drawdown(current_equity, high_water_mark)
    
    # 5% threshold per requirements
    if drawdown_pct > Decimal("5.0"):
        current_dec = _as_decimal(current_equity)
        return (
            f"HALT: Drawdown breaker triggered. Current equity {current_dec} is {drawdown_pct}% "
            f"below High Water Mark {hwm_dec} (max allowed: 5%)"
        )
    
    if hwm_updated:
        update_data["last_hwm_update"] = firestore.SERVER_TIMESTAMP
    
    if is_breached and risk_doc.exists:
        # Only set breach timestamp if not already set
        data = risk_doc.to_dict() or {}
        if not data.get("drawdown_breached_at"):
            update_data["drawdown_breached_at"] = firestore.SERVER_TIMESTAMP
            logger.critical(
                f"🚨 KILL-SWITCH TRIGGERED! Drawdown {drawdown*100:.2f}% exceeds "
                f"threshold {threshold*100:.2f}%. Trading disabled."
            )
    
    # Clear breach timestamp if recovered
    if not is_breached and risk_doc.exists:
        data = risk_doc.to_dict() or {}
        if data.get("drawdown_breached_at"):
            update_data["drawdown_breached_at"] = None
            logger.info(
                f"✅ Drawdown recovered to {drawdown*100:.2f}%. Trading re-enabled."
            )
    
    # Write to Firestore
    risk_doc_ref.set(update_data, merge=True)
    
    logger.info(
        f"Risk state updated: HWM=${hwm}, Equity=${current_equity}, "
        f"Drawdown={drawdown*100:.2f}%, Trading={'ENABLED' if trading_enabled else 'DISABLED'}"
    )
    
    return {
        "high_water_mark": hwm,
        "current_equity": current_equity,
        "drawdown_percent": drawdown,
        "trading_enabled": trading_enabled,
        "hwm_updated": hwm_updated,
    }


def _check_trade_size(
    trade_notional: float,
    buying_power: str
) -> Optional[str]:
    """
    Check if trading is currently enabled based on risk management state.
    
    This is a fast read-only check for the signal generator to use.
    
    Args:
        trade_notional: Dollar value of the proposed trade
        buying_power: Available buying power (as string)
    
    Returns:
        Tuple of (trading_enabled, reason)
        - trading_enabled: True if trading is allowed
        - reason: Optional explanation if trading is disabled
    """
    bp_dec = _as_decimal(buying_power)
    trade_dec = Decimal(str(trade_notional))
    
    if bp_dec <= 0:
        return (
            f"KILL-SWITCH: Buying power is {bp_dec}. "
            "Cannot validate trade size."
        )
    
    # Calculate max allowed: 5% of buying power
    max_allowed = bp_dec * Decimal("0.05")
    
    if trade_dec > max_allowed:
        size_pct = (trade_dec / bp_dec) * Decimal("100")
        return (
            f"KILL-SWITCH: Trade size {trade_dec} ({size_pct:.2f}% of buying power) "
            f"exceeds maximum allowed {max_allowed} "
            f"(5% of buying power {bp_dec})"
        )
    
    return None


def validate_trade_risk(
    account_snapshot: AccountSnapshot,
    trade_request: TradeRequest,
    db: Optional[firestore.Client] = None
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
    
    # Check 1: High Water Mark drawdown check (5% threshold)
    high_water_mark = _get_high_water_mark(db=db)
    hwm_error = _check_high_water_mark(account_snapshot.equity, high_water_mark)
    if hwm_error:
        logger.error("Trade rejected: %s", hwm_error)
        return RiskCheckResult(allowed=False, reason=hwm_error)
    
    # Check 2: Trade size as percentage of buying power
    trade_size_error = _check_trade_size(trade_request.notional_usd, account_snapshot.buying_power)
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
