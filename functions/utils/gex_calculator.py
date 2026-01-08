"""
GEX (Gamma Exposure) Calculator for Institutional Data

This module fetches real-time option chains from Alpaca and calculates
Gamma Exposure levels to determine market regime (volatility expectations).

GEX Formula:
    GEX = Gamma × Open Interest × 100 × Underlying Price

Market Regimes:
    - Positive GEX (Net Long Gamma): Market stabilizing, dealers hedge by selling rallies/buying dips
    - Negative GEX (Net Short Gamma): Market volatile, dealers amplify moves by buying rallies/selling dips

The GEX "zero gamma" level acts as a support/resistance level where dealer hedging behavior changes.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from firebase_admin import firestore

logger = logging.getLogger(__name__)

from backend.config.alpaca_env import load_alpaca_auth_env


def _get_alpaca_headers() -> Dict[str, str]:
    """Get Alpaca API headers from environment variables."""
    auth = load_alpaca_auth_env()
    return auth.headers


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, returning default if conversion fails."""
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


def fetch_underlying_price(symbol: str, headers: Dict[str, str]) -> float:
    """
    Fetch the current underlying price for a symbol from Alpaca.
    
    Args:
        symbol: The underlying symbol (e.g., "SPY", "QQQ")
        headers: Alpaca API headers
        
    Returns:
        Current price of the underlying
        
    Raises:
        RuntimeError: If unable to fetch price
    """
    url = f"https://data.alpaca.markets/v2/stocks/{symbol}/trades/latest"
    params = {"feed": "iex"}
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        trade = data.get("trade", {})
        price = _safe_float(trade.get("p") or trade.get("price"))
        
        if price > 0:
            return price
            
    except Exception as e:
        logger.warning(f"Failed to fetch latest trade for {symbol}: {e}")
    
    # Fallback to quote
    try:
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        quote = data.get("quote", {})
        bid = _safe_float(quote.get("bp") or quote.get("bid_price"))
        ask = _safe_float(quote.get("ap") or quote.get("ask_price"))
        
        if bid > 0 and ask > 0:
            return (bid + ask) / 2.0
            
    except Exception as e:
        logger.error(f"Failed to fetch quote for {symbol}: {e}")
    
    raise RuntimeError(f"Unable to fetch price for {symbol}")


def fetch_option_snapshots(
    underlying: str,
    headers: Dict[str, str],
    feed: str = "indicative",
    max_pages: int = 5,
) -> Dict[str, Any]:
    """
    Fetch option chain snapshots for an underlying symbol from Alpaca.
    
    Args:
        underlying: The underlying symbol (e.g., "SPY", "QQQ")
        headers: Alpaca API headers
        feed: Options feed type (default: "indicative")
        max_pages: Maximum number of pages to fetch
        
    Returns:
        Dictionary of option snapshots keyed by option symbol
    """
    url = f"https://data.alpaca.markets/v1beta1/options/snapshots/{underlying}"
    
    all_snapshots: Dict[str, Any] = {}
    page_token: Optional[str] = None
    pages_fetched = 0
    
    for _ in range(max_pages):
        params: Dict[str, Any] = {"feed": feed}
        if page_token:
            params["page_token"] = page_token
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json() or {}
            
            snapshots = data.get("snapshots") or {}
            if isinstance(snapshots, dict):
                all_snapshots.update(snapshots)
            
            pages_fetched += 1
            page_token = data.get("next_page_token")
            
            if not page_token:
                break
                
        except Exception as e:
            logger.error(f"Failed to fetch option snapshots for {underlying}: {e}")
            break
    
    logger.info(
        f"Fetched {len(all_snapshots)} option snapshots for {underlying} "
        f"({pages_fetched} pages)"
    )
    
    return all_snapshots


def calculate_strike_gex(
    snapshot: Dict[str, Any],
    underlying_price: float,
    option_type: str,
) -> float:
    """
    Calculate GEX (Gamma Exposure) for a single option contract.
    
    GEX Formula:
        GEX = Gamma × Open Interest × 100 × Underlying Price
        
    Note: For puts, GEX is negative (dealers are short gamma on puts they sell)
    
    Args:
        snapshot: Option snapshot data from Alpaca
        underlying_price: Current price of underlying
        option_type: "call" or "put"
        
    Returns:
        Gamma exposure value (can be negative)
    """
    # Extract Greeks from snapshot
    greeks = snapshot.get("greeks", {})
    if not greeks:
        return 0.0
    
    gamma = _safe_float(greeks.get("gamma"))
    
    # Extract Open Interest
    # Open interest might be in different locations depending on API version
    open_interest = _safe_float(
        snapshot.get("open_interest") or 
        snapshot.get("openInterest") or
        snapshot.get("latestQuote", {}).get("open_interest")
    )
    
    if gamma == 0.0 or open_interest == 0.0:
        return 0.0
    
    # Calculate GEX
    # Each option contract controls 100 shares
    gex = gamma * open_interest * 100 * underlying_price
    
    # For puts, GEX contribution is negative (dealers short gamma on puts)
    if option_type.lower() == "put":
        gex = -gex
    
    return gex


def parse_option_symbol(option_symbol: str) -> Optional[Dict[str, Any]]:
    """
    Parse OCC option symbol format.
    
    Format: SYMBOL[YY][MM][DD][C/P][STRIKE]
    Example: SPY241231C00550000 = SPY Call expiring 2024-12-31 at strike $550
    
    Args:
        option_symbol: OCC format option symbol
        
    Returns:
        Dictionary with parsed components or None if parsing fails
    """
    try:
        # Standard OCC format: 6 chars symbol, 6 digits date, C/P, 8 digits strike
        if len(option_symbol) < 15:
            return None
        
        # Find the C or P (call/put indicator)
        cp_index = -1
        for i, char in enumerate(option_symbol):
            if char in ['C', 'P']:
                cp_index = i
                break
        
        if cp_index == -1:
            return None
        
        underlying = option_symbol[:cp_index-6].strip()
        date_str = option_symbol[cp_index-6:cp_index]
        option_type = "call" if option_symbol[cp_index] == 'C' else "put"
        strike_str = option_symbol[cp_index+1:]
        
        # Parse strike: last 8 digits represent strike * 1000
        strike = int(strike_str) / 1000.0
        
        return {
            "underlying": underlying,
            "date": date_str,
            "type": option_type,
            "strike": strike,
        }
    except Exception as e:
        logger.debug(f"Failed to parse option symbol {option_symbol}: {e}")
        return None


def calculate_total_gex(
    underlying: str,
    snapshots: Dict[str, Any],
    underlying_price: float,
) -> Dict[str, Any]:
    """
    Calculate total GEX across all strikes for an underlying.
    
    Args:
        underlying: Underlying symbol
        snapshots: Dictionary of option snapshots
        underlying_price: Current underlying price
        
    Returns:
        Dictionary with GEX analysis including:
        - total_gex: Net gamma exposure
        - call_gex: Total call GEX
        - put_gex: Total put GEX (negative)
        - strikes: List of GEX by strike
    """
    call_gex_total = 0.0
    put_gex_total = 0.0
    strike_gex: Dict[float, Dict[str, float]] = {}
    
    for option_symbol, snapshot in snapshots.items():
        parsed = parse_option_symbol(option_symbol)
        if not parsed:
            continue
        
        option_type = parsed["type"]
        strike = parsed["strike"]
        
        gex = calculate_strike_gex(snapshot, underlying_price, option_type)
        
        if option_type == "call":
            call_gex_total += gex
        else:
            put_gex_total += gex
        
        # Aggregate by strike
        if strike not in strike_gex:
            strike_gex[strike] = {"call_gex": 0.0, "put_gex": 0.0, "net_gex": 0.0}
        
        if option_type == "call":
            strike_gex[strike]["call_gex"] += gex
        else:
            strike_gex[strike]["put_gex"] += gex
        
        strike_gex[strike]["net_gex"] += gex
    
    # Sort strikes and find zero gamma level
    sorted_strikes = sorted(strike_gex.items())
    zero_gamma_strike = None
    
    # Find the strike where GEX crosses zero (approximate zero gamma level)
    for i in range(len(sorted_strikes) - 1):
        current_strike, current_data = sorted_strikes[i]
        next_strike, next_data = sorted_strikes[i + 1]
        
        current_gex = current_data["net_gex"]
        next_gex = next_data["net_gex"]
        
        # Check if GEX crosses zero between these strikes
        if (current_gex >= 0 and next_gex < 0) or (current_gex < 0 and next_gex >= 0):
            # Linear interpolation to find approximate zero level
            if abs(next_gex - current_gex) > 1e-9:
                weight = abs(current_gex) / abs(next_gex - current_gex)
                zero_gamma_strike = current_strike + (next_strike - current_strike) * weight
            else:
                zero_gamma_strike = current_strike
            break
    
    total_gex = call_gex_total + put_gex_total
    
    return {
        "underlying": underlying,
        "underlying_price": underlying_price,
        "total_gex": total_gex,
        "call_gex": call_gex_total,
        "put_gex": put_gex_total,
        "zero_gamma_strike": zero_gamma_strike,
        "num_strikes": len(strike_gex),
        "strikes": [
            {
                "strike": strike,
                "call_gex": data["call_gex"],
                "put_gex": data["put_gex"],
                "net_gex": data["net_gex"],
            }
            for strike, data in sorted_strikes
        ],
    }


def determine_market_regime(
    spy_analysis: Dict[str, Any],
    qqq_analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Determine overall market regime based on GEX from SPY and QQQ.
    
    Market Regimes:
    - Positive GEX: Dealers are long gamma → stabilizing effect (sell rallies, buy dips)
    - Negative GEX: Dealers are short gamma → amplifying effect (buy rallies, sell dips)
    
    Args:
        spy_analysis: GEX analysis for SPY
        qqq_analysis: GEX analysis for QQQ
        
    Returns:
        Market regime analysis
    """
    spy_gex = spy_analysis.get("total_gex", 0.0)
    qqq_gex = qqq_analysis.get("total_gex", 0.0)
    
    spy_price = spy_analysis.get("underlying_price", 0.0)
    qqq_price = qqq_analysis.get("underlying_price", 0.0)
    
    # Weight SPY more heavily (larger, more liquid)
    spy_weight = 0.7
    qqq_weight = 0.3
    
    weighted_gex = (spy_gex * spy_weight) + (qqq_gex * qqq_weight)
    
    # Determine regime
    if weighted_gex > 0:
        regime = "positive_gex"
        regime_label = "Stabilizing"
        description = (
            "Market makers are net long gamma. They will sell into rallies and "
            "buy into dips, providing a stabilizing effect. Expect lower volatility."
        )
    else:
        regime = "negative_gex"
        regime_label = "Volatile"
        description = (
            "Market makers are net short gamma. They will buy into rallies and "
            "sell into dips, amplifying price moves. Expect higher volatility."
        )
    
    # Calculate relative positioning (how far from ATM is zero gamma)
    spy_zero_gamma = spy_analysis.get("zero_gamma_strike")
    qqq_zero_gamma = qqq_analysis.get("zero_gamma_strike")
    
    spy_zero_gamma_pct = None
    if spy_zero_gamma and spy_price > 0:
        spy_zero_gamma_pct = ((spy_zero_gamma - spy_price) / spy_price) * 100
    
    qqq_zero_gamma_pct = None
    if qqq_zero_gamma and qqq_price > 0:
        qqq_zero_gamma_pct = ((qqq_zero_gamma - qqq_price) / qqq_price) * 100
    
    return {
        "regime": regime,
        "regime_label": regime_label,
        "description": description,
        "weighted_gex": weighted_gex,
        "spy": {
            "gex": spy_gex,
            "price": spy_price,
            "zero_gamma_strike": spy_zero_gamma,
            "zero_gamma_pct_from_price": spy_zero_gamma_pct,
        },
        "qqq": {
            "gex": qqq_gex,
            "price": qqq_price,
            "zero_gamma_strike": qqq_zero_gamma,
            "zero_gamma_pct_from_price": qqq_zero_gamma_pct,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def save_market_regime_to_firestore(
    db: firestore.Client,
    regime_data: Dict[str, Any],
) -> None:
    """
    Save market regime data to Firestore at systemStatus/market_regime.
    
    Args:
        db: Firestore client
        regime_data: Market regime analysis data
    """
    doc_ref = db.collection("systemStatus").document("market_regime")
    
    # Add metadata
    data = {
        **regime_data,
        "updated_at": firestore.SERVER_TIMESTAMP,
        "source": "gex_calculator",
        "version": "1.0",
    }
    
    doc_ref.set(data, merge=True)
    logger.info(f"Saved market regime to Firestore: {regime_data['regime']}")


def calculate_and_update_gex(
    db: firestore.Client,
    symbols: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Main function to calculate GEX and update market regime in Firestore.
    
    Args:
        db: Firestore client
        symbols: List of symbols to analyze (default: ["SPY", "QQQ"])
        
    Returns:
        Market regime analysis
    """
    if symbols is None:
        symbols = ["SPY", "QQQ"]
    
    headers = _get_alpaca_headers()
    
    analyses = {}
    
    for symbol in symbols:
        try:
            logger.info(f"Calculating GEX for {symbol}...")
            
            # Fetch underlying price
            underlying_price = fetch_underlying_price(symbol, headers)
            logger.info(f"{symbol} price: ${underlying_price:.2f}")
            
            # Fetch option snapshots
            snapshots = fetch_option_snapshots(symbol, headers)
            
            if not snapshots:
                logger.warning(f"No option snapshots found for {symbol}")
                continue
            
            # Calculate GEX
            analysis = calculate_total_gex(symbol, snapshots, underlying_price)
            analyses[symbol] = analysis
            
            logger.info(
                f"{symbol} GEX: Total=${analysis['total_gex']:,.0f}, "
                f"Calls=${analysis['call_gex']:,.0f}, "
                f"Puts=${analysis['put_gex']:,.0f}, "
                f"Zero Gamma Strike={analysis.get('zero_gamma_strike', 'N/A')}"
            )
            
        except Exception as e:
            logger.error(f"Failed to calculate GEX for {symbol}: {e}", exc_info=True)
    
    if "SPY" not in analyses or "QQQ" not in analyses:
        raise RuntimeError("Failed to calculate GEX for required symbols (SPY, QQQ)")
    
    # Determine market regime
    regime_data = determine_market_regime(analyses["SPY"], analyses["QQQ"])
    
    logger.info(
        f"Market Regime: {regime_data['regime_label']} "
        f"(Weighted GEX: ${regime_data['weighted_gex']:,.0f})"
    )
    
    # Save to Firestore
    save_market_regime_to_firestore(db, regime_data)
    
    return regime_data


if __name__ == "__main__":
    # For local testing
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    
    from firebase_admin import firestore as fs_admin
    from backend.persistence.firebase_client import get_firestore_client
    
    db = get_firestore_client()
    result = calculate_and_update_gex(db)
    
    print("\n" + "="*80)
    print("Market Regime Analysis")
    print("="*80)
    print(f"Regime: {result['regime_label']}")
    print(f"Description: {result['description']}")
    print(f"\nSPY: ${result['spy']['price']:.2f}, GEX: ${result['spy']['gex']:,.0f}")
    print(f"QQQ: ${result['qqq']['price']:.2f}, GEX: ${result['qqq']['gex']:,.0f}")
    print(f"\nWeighted GEX: ${result['weighted_gex']:,.0f}")
    print("="*80)
