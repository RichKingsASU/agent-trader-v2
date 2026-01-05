"""
Congressional Alpha Tracker Strategy

Implements a "whale tracking" strategy that copies trades from high-profile politicians
("Policy Whales") who have demonstrated strong trading performance.

Strategy Logic:
1. Monitor congressional stock disclosures
2. Identify trades from "Policy Whales" (e.g., Nancy Pelosi)
3. Weight trades based on:
   - Politician's historical performance (whale multiplier)
   - Committee relevance (industry-specific bonus)
   - Transaction size
4. Generate copy-trade signals

Contract:
- implement: on_market_event(event: dict) -> list[dict] | dict | None
- input event is a JSON object matching backend.strategy_runner.protocol.MarketEvent
- output intents are JSON objects matching backend.strategy_runner.protocol.OrderIntent
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Policy Whale Configuration
# These politicians are considered "whales" - high-profile traders with strong track records
POLICY_WHALES = {
    # House
    "Nancy Pelosi": {"weight_multiplier": 1.5, "min_confidence": 0.7},
    "Paul Pelosi": {"weight_multiplier": 1.5, "min_confidence": 0.7},
    "Brian Higgins": {"weight_multiplier": 1.3, "min_confidence": 0.65},
    "Josh Gottheimer": {"weight_multiplier": 1.3, "min_confidence": 0.65},
    "Marjorie Taylor Greene": {"weight_multiplier": 1.2, "min_confidence": 0.6},
    
    # Senate
    "Tommy Tuberville": {"weight_multiplier": 1.4, "min_confidence": 0.7},
    "Dan Sullivan": {"weight_multiplier": 1.3, "min_confidence": 0.65},
    "Shelley Moore Capito": {"weight_multiplier": 1.3, "min_confidence": 0.65},
    "John Hickenlooper": {"weight_multiplier": 1.2, "min_confidence": 0.6},
}

# Committee weighting: Higher weight for relevant industries
COMMITTEE_WEIGHTS = {
    # Defense & Military
    "Armed Services": {
        "tickers": ["LMT", "RTX", "NOC", "GD", "BA", "LHX", "HII", "TXT"],
        "bonus": 0.4,
    },
    
    # Technology
    "Science, Space, and Technology": {
        "tickers": ["AAPL", "GOOGL", "GOOG", "MSFT", "META", "NVDA", "AMD", "INTC", "QCOM"],
        "bonus": 0.35,
    },
    "Energy and Commerce": {
        "tickers": ["AAPL", "GOOGL", "GOOG", "META", "T", "VZ", "CMCSA", "TMUS"],
        "bonus": 0.3,
    },
    
    # Finance
    "Financial Services": {
        "tickers": ["JPM", "BAC", "GS", "MS", "C", "WFC", "BLK", "SCHW"],
        "bonus": 0.35,
    },
    "Banking, Housing, and Urban Affairs": {
        "tickers": ["JPM", "BAC", "GS", "MS", "C", "WFC", "USB", "PNC"],
        "bonus": 0.35,
    },
    
    # Healthcare
    "Health, Education, Labor, and Pensions": {
        "tickers": ["PFE", "JNJ", "UNH", "CVS", "ABBV", "MRK", "LLY", "TMO"],
        "bonus": 0.3,
    },
    
    # Energy
    "Natural Resources": {
        "tickers": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "PSX"],
        "bonus": 0.3,
    },
    "Energy and Natural Resources": {
        "tickers": ["XOM", "CVX", "COP", "SLB", "EOG", "OXY", "PSX"],
        "bonus": 0.3,
    },
    
    # Agriculture
    "Agriculture": {
        "tickers": ["ADM", "BG", "DE", "CTVA", "MOS", "CF", "NTR"],
        "bonus": 0.25,
    },
    
    # Transportation
    "Transportation and Infrastructure": {
        "tickers": ["UAL", "DAL", "AAL", "LUV", "UPS", "FDX", "NSC", "UNP"],
        "bonus": 0.25,
    },
    
    # Appropriations (universal relevance)
    "Appropriations": {
        "tickers": ["*"],
        "bonus": 0.2,
    },
}

# High-conviction tickers - Large cap tech and defense
HIGH_CONVICTION_TICKERS = {
    "NVDA", "AAPL", "MSFT", "GOOGL", "GOOG", "META", "AMZN", "TSLA",
    "LMT", "RTX", "NOC", "GD", "BA",
}

# Configuration
MIN_TRANSACTION_SIZE = 15000.0  # Minimum $15k transaction
MAX_POSITION_SIZE_PCT = 0.05  # Max 5% of portfolio per trade
PURCHASE_ONLY = True  # Only copy purchases, not sales


def calculate_committee_weight(committees: List[str], ticker: str) -> float:
    """
    Calculate weight bonus based on committee membership and ticker relevance.
    
    Args:
        committees: List of committee names
        ticker: Stock ticker symbol
        
    Returns:
        float: Bonus multiplier (0.0 = no bonus, 0.4 = 40% bonus, etc.)
    """
    total_bonus = 0.0
    
    for committee in committees:
        if committee in COMMITTEE_WEIGHTS:
            config = COMMITTEE_WEIGHTS[committee]
            relevant_tickers = config["tickers"]
            bonus = config["bonus"]
            
            # Check if ticker is relevant to this committee
            if "*" in relevant_tickers or ticker in relevant_tickers:
                total_bonus += bonus
    
    # Cap total bonus at 1.0 (100%)
    return min(total_bonus, 1.0)


def calculate_position_size(
    transaction_amount_midpoint: float,
    whale_multiplier: float,
    committee_bonus: float,
    is_high_conviction: bool,
) -> float:
    """
    Calculate position size based on multiple factors.
    
    Args:
        transaction_amount_midpoint: Midpoint of disclosed transaction range
        whale_multiplier: Multiplier based on politician's track record
        committee_bonus: Bonus based on committee relevance
        is_high_conviction: Whether ticker is in high-conviction list
        
    Returns:
        float: Suggested position size in dollars
    """
    # Base size is a fraction of politician's transaction
    base_size = transaction_amount_midpoint * 0.1  # Copy 10% of their trade
    
    # Apply whale multiplier
    size = base_size * whale_multiplier
    
    # Apply committee bonus
    size = size * (1.0 + committee_bonus)
    
    # Apply high-conviction bonus
    if is_high_conviction:
        size = size * 1.3  # 30% bonus for high-conviction tickers
    
    # Floor at $1000, cap at $50,000 per trade
    return max(1000.0, min(size, 50000.0))


def calculate_confidence(
    whale_multiplier: float,
    committee_bonus: float,
    is_high_conviction: bool,
    transaction_amount: float,
) -> float:
    """
    Calculate confidence score for the trade signal.
    
    Returns:
        float: Confidence between 0.0 and 1.0
    """
    # Base confidence from whale multiplier (normalized)
    base_confidence = (whale_multiplier - 1.0) / 0.5  # 1.0-1.5 -> 0.0-1.0
    base_confidence = max(0.0, min(base_confidence, 1.0))
    
    # Bonus from committee relevance
    committee_score = committee_bonus * 0.5  # Up to 0.5 bonus
    
    # Bonus for high-conviction tickers
    conviction_score = 0.15 if is_high_conviction else 0.0
    
    # Bonus for large transactions (signals conviction)
    size_score = 0.0
    if transaction_amount >= 100000:
        size_score = 0.15
    elif transaction_amount >= 50000:
        size_score = 0.10
    elif transaction_amount >= 25000:
        size_score = 0.05
    
    # Combine scores
    total_confidence = base_confidence + committee_score + conviction_score + size_score
    
    # Cap at 0.95 (never 100% confident)
    return min(total_confidence, 0.95)


def on_market_event(event: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """
    Process congressional disclosure market events and generate copy-trade signals.
    
    Args:
        event: Market event containing congressional trade disclosure
        
    Returns:
        List of order intents, or None if no action
    """
    # Extract event data
    symbol = event.get("symbol", "").upper()
    source = event.get("source", "")
    payload = event.get("payload", {}) or {}
    
    # Only process congressional disclosure events
    if source != "congressional_disclosure":
        return None
    
    # Extract trade details
    politician = payload.get("politician", "")
    transaction_type = payload.get("transaction_type", "").lower()
    amount_min = payload.get("amount_min", 0.0)
    amount_max = payload.get("amount_max", 0.0)
    amount_midpoint = payload.get("amount_midpoint", 0.0)
    committees = payload.get("committees", [])
    chamber = payload.get("chamber", "")
    party = payload.get("party", "")
    
    # Filter 1: Only process purchases (not sales)
    if PURCHASE_ONLY and transaction_type != "purchase":
        return None
    
    # Filter 2: Only track "Policy Whales"
    if politician not in POLICY_WHALES:
        return None
    
    whale_config = POLICY_WHALES[politician]
    whale_multiplier = whale_config["weight_multiplier"]
    min_confidence = whale_config.get("min_confidence", 0.6)
    
    # Filter 3: Minimum transaction size
    if amount_midpoint < MIN_TRANSACTION_SIZE:
        return None
    
    # Calculate factors
    committee_bonus = calculate_committee_weight(committees, symbol)
    is_high_conviction = symbol in HIGH_CONVICTION_TICKERS
    
    # Calculate confidence
    confidence = calculate_confidence(
        whale_multiplier=whale_multiplier,
        committee_bonus=committee_bonus,
        is_high_conviction=is_high_conviction,
        transaction_amount=amount_midpoint,
    )
    
    # Filter 4: Minimum confidence threshold
    if confidence < min_confidence:
        return None
    
    # Calculate position size
    position_size = calculate_position_size(
        transaction_amount_midpoint=amount_midpoint,
        whale_multiplier=whale_multiplier,
        committee_bonus=committee_bonus,
        is_high_conviction=is_high_conviction,
    )
    
    # Calculate quantity (assuming we'll get current price from execution engine)
    # For now, use notional value and let execution engine determine quantity
    
    # Generate order intent
    intent = {
        "intent_id": f"congress_{uuid.uuid4().hex[:12]}",
        "ts": event.get("ts"),
        "symbol": symbol,
        "side": "buy" if transaction_type == "purchase" else "sell",
        "qty": 0,  # Will be calculated by execution engine based on notional
        "order_type": "market",
        "time_in_force": "day",
        "client_tag": "congressional_alpha",
        "metadata": {
            "strategy": "congressional_alpha_tracker",
            "politician": politician,
            "chamber": chamber,
            "party": party,
            "transaction_type": transaction_type,
            "politician_amount": f"${amount_min:,.0f}-${amount_max:,.0f}",
            "politician_amount_midpoint": amount_midpoint,
            "committees": committees,
            "whale_multiplier": whale_multiplier,
            "committee_bonus": committee_bonus,
            "is_high_conviction": is_high_conviction,
            "confidence": confidence,
            "suggested_notional": position_size,
            "reasoning": (
                f"Copying {politician}'s {transaction_type} of {symbol}. "
                f"Confidence: {confidence:.1%}. "
                f"Whale multiplier: {whale_multiplier}x. "
                + (f"Committee bonus: {committee_bonus:.0%}. " if committee_bonus > 0 else "")
                + (f"High-conviction ticker. " if is_high_conviction else "")
                + f"Original trade: ${amount_midpoint:,.0f}."
            ),
        },
    }
    
    return [intent]


# Additional helper functions for strategy management

def get_tracked_politicians() -> List[str]:
    """Return list of all tracked policy whales."""
    return list(POLICY_WHALES.keys())


def get_committee_tickers(committee: str) -> List[str]:
    """Return list of tickers relevant to a committee."""
    if committee in COMMITTEE_WEIGHTS:
        return COMMITTEE_WEIGHTS[committee]["tickers"]
    return []


def is_high_conviction_ticker(ticker: str) -> bool:
    """Check if ticker is in high-conviction list."""
    return ticker in HIGH_CONVICTION_TICKERS


def get_politician_stats(politician: str) -> Optional[Dict[str, Any]]:
    """Get configuration stats for a politician."""
    if politician in POLICY_WHALES:
        config = POLICY_WHALES[politician]
        return {
            "name": politician,
            "weight_multiplier": config["weight_multiplier"],
            "min_confidence": config.get("min_confidence", 0.6),
            "is_tracked": True,
        }
    return None
