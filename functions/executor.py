"""
Trade Executor - Phase 4: The Trade Executor (OMS)

Provides trade math utilities using decimal.Decimal for precision.
Handles order sizing calculations and marketable limit price generation.
"""

import uuid
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Dict, Any, Optional
from datetime import datetime


def generate_client_order_id(prefix: str = "AT") -> str:
    """
    Generate a unique client order ID for crash recovery and audit trails.
    
    Format: AT_{timestamp}_{uuid}
    Example: AT_20231230123045_a1b2c3d4
    
    Args:
        prefix: Prefix for the order ID (default: "AT" for AgentTrader)
    
    Returns:
        Unique client order ID string
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    return f"{prefix}_{timestamp}_{unique_id}"


def calculate_order_notional(
    buying_power: str,
    allocation_pct: float,
    max_position_size: Optional[float] = None
) -> Decimal:
    """
    Calculate order notional amount using Decimal for precision.
    
    Args:
        buying_power: Available buying power as string (to preserve precision)
        allocation_pct: Target allocation as percentage (0.0 to 1.0)
        max_position_size: Optional maximum position size in USD
    
    Returns:
        Order notional amount as Decimal
    """
    # Convert to Decimal for precise calculation
    bp = Decimal(str(buying_power))
    alloc = Decimal(str(allocation_pct))
    
    # Calculate target notional
    notional = bp * alloc
    
    # Apply max position size if specified
    if max_position_size is not None:
        max_size = Decimal(str(max_position_size))
        notional = min(notional, max_size)
    
    # Round down to 2 decimal places (cents)
    return notional.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def calculate_limit_price(
    current_price: float,
    side: str,
    slippage_buffer_pct: float = 0.005
) -> Decimal:
    """
    Calculate marketable limit price for slippage protection.
    
    For BUY orders: set limit 0.5% above current ask
    For SELL orders: set limit 0.5% below current bid
    
    Args:
        current_price: Current market price (ask for buy, bid for sell)
        side: Order side ("buy" or "sell")
        slippage_buffer_pct: Slippage buffer percentage (default: 0.005 = 0.5%)
    
    Returns:
        Limit price as Decimal, rounded appropriately
    """
    price = Decimal(str(current_price))
    buffer = Decimal(str(slippage_buffer_pct))
    
    if side.lower() == "buy":
        # Buy: add buffer to protect against price spikes
        limit_price = price * (Decimal("1") + buffer)
        # Round up to ensure fill
        return limit_price.quantize(Decimal("0.01"), rounding=ROUND_UP)
    elif side.lower() == "sell":
        # Sell: subtract buffer to protect against price drops
        limit_price = price * (Decimal("1") - buffer)
        # Round down to ensure fill
        return limit_price.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    else:
        raise ValueError(f"Invalid side: {side}. Must be 'buy' or 'sell'")


def calculate_position_size_shares(
    notional: Decimal,
    current_price: float
) -> Decimal:
    """
    Calculate position size in shares from notional amount.
    
    Args:
        notional: Notional amount in USD
        current_price: Current price per share
    
    Returns:
        Number of shares as Decimal
    """
    price = Decimal(str(current_price))
    
    if price <= 0:
        raise ValueError("Current price must be positive")
    
    # Calculate shares
    shares = notional / price
    
    # Round down to avoid exceeding buying power
    # Alpaca supports fractional shares, so we keep 6 decimal places
    return shares.quantize(Decimal("0.000001"), rounding=ROUND_DOWN)


def validate_order_params(
    symbol: str,
    side: str,
    notional: Decimal,
    limit_price: Optional[Decimal] = None
) -> Dict[str, Any]:
    """
    Validate order parameters before submission.
    
    Args:
        symbol: Stock symbol
        side: Order side ("buy" or "sell")
        notional: Order notional amount
        limit_price: Optional limit price
    
    Returns:
        Validation result dict with 'valid' boolean and 'errors' list
    """
    errors = []
    
    # Validate symbol
    if not symbol or not isinstance(symbol, str):
        errors.append("Invalid symbol: must be non-empty string")
    
    # Validate side
    if side.lower() not in ["buy", "sell"]:
        errors.append("Invalid side: must be 'buy' or 'sell'")
    
    # Validate notional
    if notional <= 0:
        errors.append("Invalid notional: must be positive")
    
    # Alpaca minimum order is $1
    if notional < Decimal("1.00"):
        errors.append("Notional too small: minimum order is $1.00")
    
    # Validate limit price if provided
    if limit_price is not None and limit_price <= 0:
        errors.append("Invalid limit_price: must be positive")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors
    }


def build_audit_log_entry(
    client_order_id: str,
    symbol: str,
    side: str,
    notional: Decimal,
    order_type: str,
    limit_price: Optional[Decimal] = None,
    status: str = "pending",
    error_message: Optional[str] = None,
    alpaca_order_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build an audit log entry for trade history.
    
    Args:
        client_order_id: Unique client order ID
        symbol: Stock symbol
        side: Order side
        notional: Order notional amount
        order_type: Order type ("market" or "limit")
        limit_price: Limit price if applicable
        status: Order status
        error_message: Error message if failed
        alpaca_order_id: Alpaca's order ID if submitted
        metadata: Additional metadata
    
    Returns:
        Audit log entry dict ready for Firestore
    """
    entry = {
        "client_order_id": client_order_id,
        "symbol": symbol,
        "side": side,
        "notional": str(notional),  # Store as string to preserve precision
        "order_type": order_type,
        "status": status,
        "created_at": datetime.utcnow().isoformat(),
        "timestamp": datetime.utcnow(),  # Firestore timestamp
    }
    
    if limit_price is not None:
        entry["limit_price"] = str(limit_price)
    
    if error_message:
        entry["error_message"] = error_message
    
    if alpaca_order_id:
        entry["alpaca_order_id"] = alpaca_order_id
    
    if metadata:
        entry["metadata"] = metadata
    
    return entry
