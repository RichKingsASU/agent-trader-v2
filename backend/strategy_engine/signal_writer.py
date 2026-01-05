"""
Trading Signal Writer for Firestore

Writes trading signals to the tradingSignals collection for dashboard display.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, Optional
from uuid import UUID

from backend.persistence.firebase_client import get_firestore_client

logger = logging.getLogger(__name__)


def write_trading_signal(
    strategy_id: UUID,
    strategy_name: str,
    symbol: str,
    action: str,
    reason: str,
    signal_payload: Dict,
    did_trade: bool = False,
    paper_trade_id: Optional[UUID] = None
) -> Optional[str]:
    """
    Write a trading signal to the Firestore tradingSignals collection.
    
    This signal will be displayed in the SaaS dashboard for monitoring.
    
    Args:
        strategy_id: UUID of the strategy definition
        strategy_name: Human-readable strategy name
        symbol: Stock symbol
        action: Trading action (BUY, SELL, HOLD, flat)
        reason: Human-readable reasoning for the decision
        signal_payload: Additional structured data (sentiment scores, etc.)
        did_trade: Whether a trade was actually executed
        paper_trade_id: UUID of the executed trade (if any)
    
    Returns:
        Document ID of the created signal, or None if write failed
    """
    try:
        # Get Firestore client
        db = get_firestore_client()
        
        # Prepare signal document
        signal_doc = {
            "strategy_id": str(strategy_id),
            "strategy_name": strategy_name,
            "symbol": symbol,
            "action": action.upper() if action != "flat" else "HOLD",
            "reason": reason,
            "signal_payload": signal_payload,
            "did_trade": did_trade,
            "timestamp": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
        }
        
        # Add trade reference if available
        if paper_trade_id:
            signal_doc["paper_trade_id"] = str(paper_trade_id)
        
        # Extract key metrics for easy querying/display
        if signal_payload:
            # Add sentiment-specific fields
            if "sentiment_score" in signal_payload:
                signal_doc["sentiment_score"] = signal_payload["sentiment_score"]
            if "confidence" in signal_payload:
                signal_doc["confidence"] = signal_payload["confidence"]
            if "llm_reasoning" in signal_payload:
                signal_doc["llm_reasoning"] = signal_payload["llm_reasoning"]
            if "cash_flow_impact" in signal_payload:
                signal_doc["cash_flow_impact"] = signal_payload["cash_flow_impact"]
            if "model_id" in signal_payload:
                signal_doc["model_id"] = signal_payload["model_id"]
        
        # Write to tradingSignals collection
        doc_ref = db.collection("tradingSignals").add(signal_doc)
        doc_id = doc_ref[1].id
        
        logger.info(
            f"Wrote trading signal to Firestore: {doc_id} - "
            f"{strategy_name} {action} {symbol}"
        )
        
        return doc_id
        
    except Exception as e:
        logger.exception(f"Failed to write trading signal to Firestore: {e}")
        return None


def write_llm_sentiment_signal(
    strategy_id: UUID,
    symbol: str,
    action: str,
    reason: str,
    sentiment_score: float,
    confidence: float,
    llm_reasoning: str,
    cash_flow_impact: str,
    news_count: int,
    did_trade: bool = False,
    paper_trade_id: Optional[UUID] = None
) -> Optional[str]:
    """
    Convenience function to write an LLM sentiment signal.
    
    Args:
        strategy_id: UUID of the strategy definition
        symbol: Stock symbol
        action: Trading action (BUY, SELL, HOLD)
        reason: Human-readable reasoning
        sentiment_score: Sentiment score from -1.0 to 1.0
        confidence: Confidence level from 0.0 to 1.0
        llm_reasoning: Detailed reasoning from the LLM
        cash_flow_impact: Cash flow impact analysis
        news_count: Number of news items analyzed
        did_trade: Whether a trade was executed
        paper_trade_id: UUID of the executed trade (if any)
    
    Returns:
        Document ID of the created signal, or None if write failed
    """
    signal_payload = {
        "sentiment_score": sentiment_score,
        "confidence": confidence,
        "llm_reasoning": llm_reasoning,
        "cash_flow_impact": cash_flow_impact,
        "news_count": news_count,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "model_id": "gemini-1.5-flash"
    }
    
    return write_trading_signal(
        strategy_id=strategy_id,
        strategy_name="LLM Sentiment Alpha",
        symbol=symbol,
        action=action,
        reason=reason,
        signal_payload=signal_payload,
        did_trade=did_trade,
        paper_trade_id=paper_trade_id
    )
