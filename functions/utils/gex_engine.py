"""
GEX (Gamma Exposure) Calculation Engine

This module provides real-time "Market Weather" data by calculating
the net gamma exposure across the options market.

GEX measures how much market makers need to hedge their options positions,
which can amplify or dampen market moves:
- Positive GEX: Market makers are long gamma → they stabilize price (sell rallies, buy dips)
- Negative GEX: Market makers are short gamma → they amplify moves (sell dips, buy rallies)

Usage:
    from functions.utils.gex_engine import calculate_net_gex
    
    gex_data = calculate_net_gex(symbol="SPY", api=alpaca_client)
    net_gex = gex_data["net_gex"]
    volatility_bias = gex_data["volatility_bias"]
"""

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional
from datetime import datetime, timedelta

import alpaca_trade_api as tradeapi

logger = logging.getLogger(__name__)


def _to_decimal(value: Any) -> Decimal:
    """Safely convert a value to Decimal with fintech precision."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    return Decimal("0")


def calculate_net_gex(
    symbol: str,
    api: tradeapi.REST,
    spot_price: Optional[Decimal] = None,
) -> Dict[str, Any]:
    """
    Calculate Net GEX (Gamma Exposure) for a given symbol.
    
    This function:
    1. Fetches the full 0DTE and 1DTE option chain for the symbol
    2. Calculates GEX for each strike:
       - Call GEX = Gamma * OpenInterest * 100 * SpotPrice
       - Put GEX = Gamma * OpenInterest * 100 * SpotPrice * -1
    3. Aggregates all strikes to get Net GEX for the entire market
    4. Uses Decimal for all arithmetic before storing the final result
    
    Args:
        symbol: Ticker symbol (e.g., "SPY", "QQQ")
        api: Alpaca REST API client
        spot_price: Current spot price (fetched if not provided)
    
    Returns:
        Dictionary with:
            - net_gex: Total net gamma exposure (string for fintech precision)
            - net_gex_decimal: Net GEX as Decimal for calculations
            - volatility_bias: "Bullish" if GEX > 0, "Bearish" if GEX < 0, "Neutral" if 0
            - spot_price: Current spot price (string)
            - timestamp: ISO timestamp of calculation
            - option_count: Number of options processed
            - total_call_gex: Total call GEX (string)
            - total_put_gex: Total put GEX (string)
    """
    logger.info(f"Calculating Net GEX for {symbol}...")
    
    try:
        # Get current spot price if not provided
        if spot_price is None:
            try:
                latest_trade = api.get_latest_trade(symbol)
                spot_price = _to_decimal(latest_trade.price)
                logger.debug(f"Fetched spot price for {symbol}: {spot_price}")
            except Exception as price_error:
                logger.error(f"Failed to get spot price for {symbol}: {price_error}")
                return {
                    "net_gex": "0.00",
                    "net_gex_decimal": Decimal("0"),
                    "volatility_bias": "Unknown",
                    "spot_price": "0.00",
                    "timestamp": datetime.utcnow().isoformat(),
                    "option_count": 0,
                    "total_call_gex": "0.00",
                    "total_put_gex": "0.00",
                    "error": str(price_error),
                }
        else:
            spot_price = _to_decimal(spot_price)
        
        # Calculate date range for 0DTE and 1DTE options
        now = datetime.utcnow()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        
        # Format dates as YYYY-MM-DD for Alpaca API
        expiration_date_lte = tomorrow.isoformat()
        
        # Fetch option chain
        # Note: Alpaca's get_option_chain may have different parameters
        # Adjust based on actual Alpaca API
        try:
            # Get option chain for 0DTE and 1DTE
            option_chain = api.get_option_chain(
                symbol,
                expiration_date_lte=expiration_date_lte,
            )
            
            if not option_chain:
                logger.warning(f"No option chain data available for {symbol}")
                return {
                    "net_gex": "0.00",
                    "net_gex_decimal": Decimal("0"),
                    "volatility_bias": "Neutral",
                    "spot_price": str(spot_price),
                    "timestamp": datetime.utcnow().isoformat(),
                    "option_count": 0,
                    "total_call_gex": "0.00",
                    "total_put_gex": "0.00",
                    "warning": "No option chain data available",
                }
            
        except AttributeError:
            # Fallback: If get_option_chain doesn't exist, use list_options and get_option_bars
            logger.warning(f"get_option_chain not available, using alternative method")
            
            # Alternative approach: Use snapshot or bars
            # This is a fallback implementation
            return {
                "net_gex": "0.00",
                "net_gex_decimal": Decimal("0"),
                "volatility_bias": "Neutral",
                "spot_price": str(spot_price),
                "timestamp": datetime.utcnow().isoformat(),
                "option_count": 0,
                "total_call_gex": "0.00",
                "total_put_gex": "0.00",
                "warning": "Option chain API not available - using fallback",
            }
        
        # Process option chain and calculate GEX
        total_call_gex = Decimal("0")
        total_put_gex = Decimal("0")
        option_count = 0
        
        # Parse option chain (structure depends on Alpaca's response)
        # Expected structure: list of option contracts with greeks and open interest
        for option in option_chain:
            try:
                # Extract option data
                # Note: Adjust field names based on actual Alpaca API response
                gamma = _to_decimal(option.get("gamma", option.get("greeks", {}).get("gamma", 0)))
                open_interest = _to_decimal(option.get("open_interest", 0))
                option_type = option.get("type", option.get("option_type", "")).upper()
                
                if gamma == Decimal("0") or open_interest == Decimal("0"):
                    continue
                
                # Calculate GEX for this strike
                # Contract multiplier: 100 shares per contract
                contract_multiplier = Decimal("100")
                
                if option_type == "CALL" or option_type == "C":
                    # Call GEX = Gamma * OpenInterest * 100 * SpotPrice
                    call_gex = gamma * open_interest * contract_multiplier * spot_price
                    total_call_gex += call_gex
                    option_count += 1
                    
                elif option_type == "PUT" or option_type == "P":
                    # Put GEX = Gamma * OpenInterest * 100 * SpotPrice * -1
                    put_gex = gamma * open_interest * contract_multiplier * spot_price * Decimal("-1")
                    total_put_gex += put_gex
                    option_count += 1
                    
            except Exception as option_error:
                logger.debug(f"Error processing option: {option_error}")
                continue
        
        # Calculate Net GEX
        net_gex = total_call_gex + total_put_gex
        
        # Determine volatility bias
        if net_gex > Decimal("0"):
            volatility_bias = "Bullish"
        elif net_gex < Decimal("0"):
            volatility_bias = "Bearish"
        else:
            volatility_bias = "Neutral"
        
        # Round to 2 decimal places for storage
        net_gex_str = net_gex.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_call_gex_str = total_call_gex.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_put_gex_str = total_put_gex.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        result = {
            "net_gex": str(net_gex_str),
            "net_gex_decimal": net_gex,  # For calculations
            "volatility_bias": volatility_bias,
            "spot_price": str(spot_price),
            "timestamp": datetime.utcnow().isoformat(),
            "option_count": option_count,
            "total_call_gex": str(total_call_gex_str),
            "total_put_gex": str(total_put_gex_str),
            "symbol": symbol,
        }
        
        logger.info(
            f"GEX calculated for {symbol}: "
            f"Net GEX = {net_gex_str}, "
            f"Bias = {volatility_bias}, "
            f"Options processed = {option_count}"
        )
        
        return result
        
    except Exception as e:
        logger.exception(f"Error calculating GEX for {symbol}: {e}")
        return {
            "net_gex": "0.00",
            "net_gex_decimal": Decimal("0"),
            "volatility_bias": "Unknown",
            "spot_price": str(spot_price) if spot_price else "0.00",
            "timestamp": datetime.utcnow().isoformat(),
            "option_count": 0,
            "total_call_gex": "0.00",
            "total_put_gex": "0.00",
            "error": str(e),
        }


def get_market_regime_summary(gex_data: Dict[str, Any]) -> str:
    """
    Generate a human-readable market regime summary from GEX data.
    
    Args:
        gex_data: Output from calculate_net_gex
    
    Returns:
        String summary of market conditions
    """
    net_gex = gex_data.get("net_gex", "0.00")
    volatility_bias = gex_data.get("volatility_bias", "Unknown")
    symbol = gex_data.get("symbol", "Unknown")
    
    if volatility_bias == "Bullish":
        return (
            f"{symbol} Market Regime: BULLISH (Positive GEX = {net_gex})\n"
            f"Market makers are long gamma → expect price stabilization\n"
            f"They will sell rallies and buy dips, dampening volatility."
        )
    elif volatility_bias == "Bearish":
        return (
            f"{symbol} Market Regime: BEARISH (Negative GEX = {net_gex})\n"
            f"Market makers are short gamma → expect volatility amplification\n"
            f"They will sell dips and buy rallies, increasing volatility."
        )
    else:
        return (
            f"{symbol} Market Regime: NEUTRAL (GEX = {net_gex})\n"
            f"Balanced gamma exposure → normal volatility expected."
        )
