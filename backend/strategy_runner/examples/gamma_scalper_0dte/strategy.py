"""
0DTE Gamma Scalper Strategy

This strategy implements a delta-neutral gamma scalping approach for 0DTE options.

Core Logic:
1. Calculate Net Portfolio Delta from all open positions
2. If abs(Net Delta) > HEDGING_THRESHOLD (0.15), trigger hedge trade to neutralize delta
3. Ingest GEX (Gamma Exposure) data from Firestore
4. If GEX is negative, increase hedging frequency (tighter threshold)
5. Exit all positions at 3:45 PM ET to avoid Market-on-Close volatility

Safety:
- All calculations use Decimal for precision
- Time-based position exit at 3:45 PM ET
- Dynamic hedging based on market regime (GEX)

Contract:
- implement: on_market_event(event: dict) -> list[dict] | dict | None
- input event is a JSON object matching backend.strategy_runner.protocol.MarketEvent
- output intents are JSON objects matching backend.strategy_runner.protocol.OrderIntent
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
from backend.time.nyse_time import NYSE_TZ, parse_ts, to_nyse, utc_now

logger = logging.getLogger(__name__)

# Strategy configuration
HEDGING_THRESHOLD = Decimal("0.15")  # Base delta threshold for hedging
HEDGING_THRESHOLD_NEGATIVE_GEX = Decimal("0.10")  # Tighter threshold when GEX is negative
EXIT_TIME_ET = time(15, 45, 0)  # 3:45 PM ET - exit time to avoid MOC volatility
UNDERLYING_SYMBOL = "SPY"  # Day-1 shadow-mode safety: emit SPY intents only

# Global state (persists across market events in the same run)
_portfolio_positions: Dict[str, Dict[str, Any]] = {}
_last_gex_value: Optional[Decimal] = None
_last_gex_update: Optional[datetime] = None
_last_hedge_time: Optional[datetime] = None
_macro_event_active: bool = False
_stop_loss_multiplier: Decimal = Decimal("1.0")
_position_size_multiplier: Decimal = Decimal("1.0")
_last_macro_check: Optional[datetime] = None

# --- Shadow-mode safety latches (minimal state) ---
# Intent: prevent runaway behavior on Day-1 shadow runs.
# - one hedge trade max per NYSE day
# - after 15:45 ET: emit ONE flatten intent (SPY hedge) and halt for rest of day
_active_day_key: Optional[str] = None  # NYSE date ISO string, e.g. "2026-01-21"
_hedge_emitted_day_key: Optional[str] = None
_flatten_emitted_day_key: Optional[str] = None
_halted_day_key: Optional[str] = None
_spy_hedge_position_shares: Decimal = Decimal("0")  # signed net SPY shares we *intend* to hold via hedges


def _to_decimal(value: Any) -> Decimal:
    """Safely convert a value to Decimal with precision."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    return Decimal("0")


# Option delta scaling: delta is per-share; contracts need a multiplier (default 100)
OPTION_CONTRACT_MULTIPLIER = _to_decimal(os.getenv("OPTION_CONTRACT_MULTIPLIER", "100"))


def _parse_timestamp(ts_str: str) -> datetime:
    """Parse ISO8601 timestamp string to datetime with timezone."""
    if not ts_str:
        return utc_now()
    try:
        return parse_ts(ts_str)
    except Exception:
        return utc_now()


def _is_market_close_time(current_time: datetime) -> bool:
    """Check if current time is at or past the exit time (3:45 PM ET)."""
    et_time = to_nyse(current_time)
    return et_time.time() >= EXIT_TIME_ET


def _day_key_et(current_time: datetime) -> str:
    """Return NYSE date key for daily latches."""
    return to_nyse(current_time).date().isoformat()


def _roll_daily_latches(current_time: datetime) -> None:
    """
    Reset per-day latches when the NYSE day changes.

    Safety intent: make the strategy stateless across days in a long-lived runner,
    avoiding "yesterday's latch" preventing today's safety flatten, and ensuring
    a clean 1-hedge-per-day rule.
    """
    global _active_day_key, _hedge_emitted_day_key, _flatten_emitted_day_key, _halted_day_key
    global _spy_hedge_position_shares, _last_hedge_time

    day_key = _day_key_et(current_time)
    if _active_day_key == day_key:
        return

    _active_day_key = day_key
    _hedge_emitted_day_key = None
    _flatten_emitted_day_key = None
    _halted_day_key = None
    _spy_hedge_position_shares = Decimal("0")
    _last_hedge_time = None


def _get_net_portfolio_delta() -> Decimal:
    """
    Calculate Net Portfolio Delta from all open positions.
    
    Returns:
        Decimal: Sum of (option_delta * contracts) across tracked positions.

    Note:
        This returns *unscaled* delta in "contracts-delta" units (i.e. shares delta / 100).
        Hedge sizing converts this to shares using OPTION_CONTRACT_MULTIPLIER (default 100).
    """
    net_delta = Decimal("0")
    
    for symbol, position in _portfolio_positions.items():
        delta = _to_decimal(position.get("delta", 0))
        qty = _to_decimal(position.get("quantity", 0))
        net_delta += delta * qty
    
    return net_delta


def _update_position(symbol: str, payload: Dict[str, Any]) -> None:
    """Update or create a position in the portfolio."""
    delta = _to_decimal(payload.get("delta"))
    qty = _to_decimal(payload.get("quantity", payload.get("qty", 1)))
    price = _to_decimal(payload.get("price", payload.get("mid", payload.get("last", 0))))
    
    _portfolio_positions[symbol] = {
        "delta": delta,
        "quantity": qty,
        "price": price,
        "last_update": payload.get("ts", ""),
        "symbol": symbol,
    }


def _remove_position(symbol: str) -> None:
    """Remove a position from the portfolio."""
    if symbol in _portfolio_positions:
        del _portfolio_positions[symbol]


def _fetch_market_regime_from_firestore() -> None:
    """
    Fetch market regime data from Firestore including GEX and macro event status.
    
    Queries systemStatus/market_regime document created by the pulse function
    and macro_scraper. Updates global state with:
    - GEX (Gamma Exposure) for dynamic hedging
    - Macro event status for risk adjustments
    - Stop-loss and position size multipliers
    
    This is called periodically to keep strategy in sync with market conditions.
    """
    global _last_gex_value, _last_gex_update
    global _macro_event_active, _stop_loss_multiplier, _position_size_multiplier, _last_macro_check
    
    try:
        # Import Firestore client (only when needed to avoid import overhead)
        from google.cloud import firestore
        
        # Initialize Firestore client
        db = firestore.Client()
        
        # Query systemStatus/market_regime document
        doc_ref = db.collection('systemStatus').document('market_regime')
        doc = doc_ref.get()
        
        if doc.exists:
            regime_data = doc.to_dict()
            
            # Get SPY net_gex (primary market indicator)
            spy_data = regime_data.get('spy', {})
            gex_value = spy_data.get('net_gex')
            
            if gex_value is not None:
                _last_gex_value = _to_decimal(gex_value)
                _last_gex_update = utc_now()
                logger.info(f"Fetched GEX from Firestore: {_last_gex_value}")
            
            # Check for macro event status (added by macro_scraper)
            macro_event_detected = regime_data.get('macro_event_detected', False)
            macro_event_status = regime_data.get('macro_event_status', 'Normal')
            
            if macro_event_detected:
                _macro_event_active = True
                _stop_loss_multiplier = _to_decimal(regime_data.get('stop_loss_multiplier', 1.5))
                _position_size_multiplier = _to_decimal(regime_data.get('position_size_multiplier', 0.75))
                
                logger.warning(
                    f"MACRO EVENT ACTIVE: {macro_event_status} - "
                    f"Stop-loss multiplier: {_stop_loss_multiplier}x, "
                    f"Position size multiplier: {_position_size_multiplier}x"
                )
                
                # Log the macro events for visibility
                macro_events = regime_data.get('macro_events', [])
                for event in macro_events:
                    logger.warning(
                        f"  - {event.get('event_name')}: "
                        f"surprise={event.get('surprise_magnitude', 0):.2f}%, "
                        f"volatility={event.get('volatility_expectation')}, "
                        f"action={event.get('recommended_action')}"
                    )
            else:
                _macro_event_active = False
                _stop_loss_multiplier = Decimal("1.0")
                _position_size_multiplier = Decimal("1.0")
            
            _last_macro_check = utc_now()
            
        else:
            # Document doesn't exist - use defaults
            logger.debug("market_regime document not found, using defaults")
            _macro_event_active = False
            _stop_loss_multiplier = Decimal("1.0")
            _position_size_multiplier = Decimal("1.0")
        
        # Fallback: check environment variable for GEX
        if _last_gex_value is None:
            env_gex = os.getenv("GEX_VALUE")
            if env_gex:
                _last_gex_value = _to_decimal(env_gex)
                _last_gex_update = utc_now()
        
    except Exception as e:
        logger.warning(f"Failed to fetch market regime from Firestore: {e}")
        
        # Fallback to environment variable or cached value
        env_gex = os.getenv("GEX_VALUE")
        if env_gex:
            _last_gex_value = _to_decimal(env_gex)
            _last_gex_update = utc_now()


def _fetch_gex_from_firestore() -> Optional[Decimal]:
    """
    Fetch GEX (Gamma Exposure) data from Firestore.
    
    This is a lightweight wrapper that calls _fetch_market_regime_from_firestore()
    to get both GEX and macro event data.
    
    Returns:
        Optional[Decimal]: SPY Net GEX value if available, None otherwise
    """
    global _last_gex_value
    
    _fetch_market_regime_from_firestore()
    return _last_gex_value


def _get_hedging_threshold() -> Decimal:
    """
    Get the current hedging threshold based on market regime (GEX) and macro events.
    
    Adjustments:
    - If GEX is negative, use a tighter threshold (more frequent hedging)
    - If macro event is active, widen threshold (less frequent hedging to reduce slippage)
    
    Returns:
        Decimal: Current hedging threshold
    """
    global _macro_event_active, _stop_loss_multiplier
    
    # Fetch latest market regime data (includes GEX and macro events)
    # Only fetch if we haven't checked recently (cache for 60 seconds)
    if _last_macro_check is None or (utc_now() - _last_macro_check).total_seconds() > 60:
        _fetch_market_regime_from_firestore()
    
    base_threshold = HEDGING_THRESHOLD
    gex = _last_gex_value
    
    # Adjust for GEX regime
    if gex is not None and gex < Decimal("0"):
        # Negative GEX: market is short gamma, increase hedging frequency
        base_threshold = HEDGING_THRESHOLD_NEGATIVE_GEX
    
    # Adjust for macro events
    # During macro volatility events, we widen the hedging threshold slightly
    # to avoid over-trading in high-slippage conditions
    if _macro_event_active:
        # Widen threshold by 25% during macro events to reduce trading
        base_threshold = base_threshold * Decimal("1.25")
        logger.debug(f"Hedging threshold widened due to macro event: {base_threshold}")
    
    return base_threshold


def _calculate_hedge_quantity(net_delta: Decimal, underlying_price: Decimal) -> Decimal:
    """
    Calculate the quantity of underlying shares needed to hedge the net delta.
    
    Applies position size multiplier from macro event status to reduce exposure
    during high-volatility periods.
    
    Args:
        net_delta: Net portfolio delta to hedge
        underlying_price: Current price of underlying asset
    
    Returns:
        Decimal: Quantity to trade (positive = buy, negative = sell)
    """
    global _position_size_multiplier
    
    if underlying_price <= Decimal("0"):
        return Decimal("0")
    
    # To neutralize delta, we need to trade opposite to our delta exposure
    # If net_delta is positive (long delta), we sell shares (negative quantity)
    # If net_delta is negative (short delta), we buy shares (positive quantity)
    #
    # Shadow-mode safety:
    # net_delta is in "contracts-delta" units, so we convert to shares with the
    # standard option contract multiplier (default 100).
    hedge_qty = -(net_delta * OPTION_CONTRACT_MULTIPLIER)
    
    # Apply position size multiplier from macro event status
    # This reduces position sizes during high-volatility events
    if _position_size_multiplier != Decimal("1.0"):
        hedge_qty = hedge_qty * _position_size_multiplier
        logger.debug(
            f"Applied position size multiplier {_position_size_multiplier}: "
            f"hedge_qty adjusted to {hedge_qty}"
        )
    
    # Round to nearest whole share
    return hedge_qty.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _should_hedge(net_delta: Decimal, current_time: datetime) -> bool:
    """
    Determine if we should hedge based on delta threshold and timing.
    
    Args:
        net_delta: Current net portfolio delta
        current_time: Current timestamp
    
    Returns:
        bool: True if hedging is needed
    """
    threshold = _get_hedging_threshold()
    abs_delta = abs(net_delta)
    
    # Check if delta exceeds threshold
    if abs_delta <= threshold:
        return False
    
    # Optional: Rate limiting to avoid over-hedging
    # (e.g., don't hedge more than once per minute)
    global _last_hedge_time
    if _last_hedge_time is not None:
        time_since_last_hedge = (current_time - _last_hedge_time).total_seconds()
        if time_since_last_hedge < 60:  # 60 seconds minimum between hedges
            return False
    
    return True


def _create_flatten_order(current_time: datetime, event_id: str, ts: str) -> Optional[Dict[str, Any]]:
    """
    Create a single SPY flatten order for the hedge position.
    
    Args:
        current_time: Current timestamp
        event_id: Event ID from market event
        ts: Timestamp string from market event
    
    Returns:
        A single SPY order intent to flatten, or None if no hedge position exists.

    Safety intent:
        Day-1 shadow-mode must emit intents for ONE symbol only (SPY). We therefore
        do not emit option close intents here; we only flatten the SPY hedge that
        this strategy itself created.
    """
    global _spy_hedge_position_shares
    if _spy_hedge_position_shares == Decimal("0"):
        return None

    # If we're long shares, we sell to flatten; if short, we buy to cover.
    side = "sell" if _spy_hedge_position_shares > Decimal("0") else "buy"
    abs_qty = abs(_spy_hedge_position_shares)

    order = {
        "protocol": "v1",
        "type": "order_intent",
        "intent_id": f"flatten_{UNDERLYING_SYMBOL}_{uuid.uuid4().hex[:12]}",
        "event_id": event_id,
        "ts": ts,
        "symbol": UNDERLYING_SYMBOL,
        "side": side,
        "qty": float(abs_qty),
        "order_type": "market",
        "time_in_force": "day",
        "client_tag": "0dte_gamma_scalper_exit",
        "metadata": {
            "reason": "market_close_flatten",
            "exit_time_et": current_time.astimezone(NYSE_TZ).isoformat(),
            "strategy": "0dte_gamma_scalper",
            "spy_hedge_shares_before": str(_spy_hedge_position_shares),
        },
    }

    # We intentionally reset the hedge position on flatten intent emission so we do not
    # double-flatten if multiple events arrive after 15:45 ET.
    _spy_hedge_position_shares = Decimal("0")
    return order


def _create_hedge_order(
    underlying_symbol: str,
    hedge_qty: Decimal,
    net_delta: Decimal,
    underlying_price: Decimal,
    event_id: str,
    ts: str,
) -> Dict[str, Any]:
    """
    Create a hedge order to neutralize portfolio delta.
    
    Includes macro event metadata and applies risk adjustments.
    
    Args:
        underlying_symbol: Symbol of the underlying asset (e.g., "SPY")
        hedge_qty: Quantity to trade (positive = buy, negative = sell)
        net_delta: Current net portfolio delta
        underlying_price: Current price of underlying
        event_id: Event ID from market event
        ts: Timestamp string
    
    Returns:
        Order intent dictionary with macro event metadata
    """
    global _macro_event_active, _stop_loss_multiplier, _position_size_multiplier
    
    side = "buy" if hedge_qty > Decimal("0") else "sell"
    abs_qty = abs(hedge_qty)
    
    # Update last hedge time
    global _last_hedge_time
    _last_hedge_time = _parse_timestamp(ts)
    
    # Calculate stop-loss price (if applicable)
    # For a hedge order, we widen the stop-loss during macro events
    stop_loss_price = None
    if _macro_event_active:
        # Example: 2% stop-loss widened by multiplier
        base_stop_loss_pct = Decimal("0.02")  # 2%
        adjusted_stop_loss_pct = base_stop_loss_pct * _stop_loss_multiplier
        
        if side == "buy":
            # For buy orders, stop-loss is below entry price
            stop_loss_price = underlying_price * (Decimal("1") - adjusted_stop_loss_pct)
        else:
            # For sell orders, stop-loss is above entry price
            stop_loss_price = underlying_price * (Decimal("1") + adjusted_stop_loss_pct)
    
    metadata = {
        "reason": "delta_hedge",
        "net_delta_before": str(net_delta),
        "hedge_qty": str(hedge_qty),
        "underlying_price": str(underlying_price),
        "hedging_threshold": str(_get_hedging_threshold()),
        "gex_value": str(_last_gex_value) if _last_gex_value is not None else None,
        "strategy": "0dte_gamma_scalper",
        "macro_event_active": _macro_event_active,
    }
    
    # Add macro event metadata if active
    if _macro_event_active:
        metadata.update({
            "stop_loss_multiplier": str(_stop_loss_multiplier),
            "position_size_multiplier": str(_position_size_multiplier),
            "adjusted_stop_loss_pct": str(adjusted_stop_loss_pct) if stop_loss_price else None,
            "stop_loss_price": str(stop_loss_price) if stop_loss_price else None,
        })
    
    return {
        "protocol": "v1",
        "type": "order_intent",
        "intent_id": f"hedge_{underlying_symbol}_{uuid.uuid4().hex[:12]}",
        "event_id": event_id,
        "ts": ts,
        "symbol": underlying_symbol,
        "side": side,
        "qty": float(abs_qty),
        "order_type": "market",
        "time_in_force": "day",
        "client_tag": "0dte_gamma_scalper_hedge",
        "metadata": metadata,
    }


def on_market_event(event: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """
    Main strategy entry point - called for each market event.
    
    Strategy Logic:
    1. Update portfolio positions with latest data
    2. Check if it's time to exit (3:45 PM ET) - if yes, exit all positions
    3. Calculate Net Portfolio Delta
    4. If abs(Net Delta) > threshold, create hedge order
    5. Adjust threshold based on GEX (tighter when GEX is negative)
    
    Args:
        event: Market event dictionary with protocol structure
    
    Returns:
        List of order intents, or None/empty list if no action needed
    """
    global _flatten_emitted_day_key, _halted_day_key, _hedge_emitted_day_key, _spy_hedge_position_shares

    # Extract event data
    event_id = event.get("event_id", "")
    ts = event.get("ts", "")
    symbol = event.get("symbol", "")
    payload = event.get("payload", {}) or {}
    
    current_time = _parse_timestamp(ts)
    _roll_daily_latches(current_time)
    day_key = _day_key_et(current_time)

    # Shadow-mode safety: once halted for the NYSE day, do nothing (no intents).
    if _halted_day_key == day_key:
        return []
    
    # Safety check: Exit all positions at 3:45 PM ET
    if _is_market_close_time(current_time):
        # After 15:45 ET we emit flatten once and halt for the remainder of the day.
        # This prevents noisy repeated exit batches if the runner continues to stream events.
        if _flatten_emitted_day_key != day_key:
            flatten = _create_flatten_order(current_time, event_id, ts)
            _flatten_emitted_day_key = day_key
            _halted_day_key = day_key
            _portfolio_positions.clear()  # no stale option state after forced shutdown
            return [flatten] if flatten else []

        _halted_day_key = day_key
        return []
    
    # Update position tracking
    # Check if this is an options contract or underlying
    is_option = "delta" in payload or "greeks" in payload
    
    if is_option:
        # Update position with options data
        _update_position(symbol, payload)
    
    # Calculate Net Portfolio Delta
    net_delta = _get_net_portfolio_delta()
    
    # Check if hedging is needed
    # Shadow-mode safety: 1 trade/day maximum (one hedge intent). Flatten at 15:45 is handled above.
    if _hedge_emitted_day_key == day_key:
        return []
    if not _should_hedge(net_delta, current_time):
        return []
    
    # Determine underlying symbol for hedging
    # For options on SPY, hedge with SPY; for SPX options, use SPY as proxy
    underlying_symbol = UNDERLYING_SYMBOL  # Day-1 shadow-mode: SPY only
    
    # Extract underlying price from payload or use current symbol price if it's the underlying
    underlying_price = _to_decimal(payload.get("underlying_price", payload.get("price", 0)))
    
    if underlying_price <= Decimal("0"):
        # Can't hedge without valid underlying price
        return []
    
    # Calculate hedge quantity
    hedge_qty = _calculate_hedge_quantity(net_delta, underlying_price)
    
    if hedge_qty == Decimal("0"):
        return []
    
    # Create and return hedge order
    hedge_order = _create_hedge_order(
        underlying_symbol=underlying_symbol,
        hedge_qty=hedge_qty,
        net_delta=net_delta,
        underlying_price=underlying_price,
        event_id=event_id,
        ts=ts,
    )
    # Shadow-mode safety: latch one hedge intent per NYSE day.
    _hedge_emitted_day_key = day_key
    # Track intended SPY hedge position so we can flatten it at 15:45 ET.
    _spy_hedge_position_shares += hedge_qty

    return [hedge_order]


# Optional: Reset function for testing
def reset_strategy_state() -> None:
    """Reset all strategy state (useful for testing)."""
    global _portfolio_positions, _last_gex_value, _last_gex_update, _last_hedge_time
    global _macro_event_active, _stop_loss_multiplier, _position_size_multiplier, _last_macro_check
    global _active_day_key, _hedge_emitted_day_key, _flatten_emitted_day_key, _halted_day_key
    global _spy_hedge_position_shares
    _portfolio_positions.clear()
    _last_gex_value = None
    _last_gex_update = None
    _last_hedge_time = None
    _macro_event_active = False
    _stop_loss_multiplier = Decimal("1.0")
    _position_size_multiplier = Decimal("1.0")
    _last_macro_check = None
    _active_day_key = None
    _hedge_emitted_day_key = None
    _flatten_emitted_day_key = None
    _halted_day_key = None
    _spy_hedge_position_shares = Decimal("0")
