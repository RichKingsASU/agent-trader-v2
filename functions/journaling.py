"""
Automated Trading Journal with AI Review.

Firestore Trigger: Analyzes closed shadow trades using Gemini 1.5 Flash.
Provides quant-grade feedback on exit timing and strategy optimization.
"""

import logging
from decimal import Decimal
from typing import Dict, Any, Optional
from datetime import datetime

import vertexai
from vertexai.generative_models import GenerativeModel
from firebase_admin import firestore
from firebase_functions import firestore_fn, options

logger = logging.getLogger(__name__)

# Initialize Vertex AI (reuse initialization from main.py pattern)
def _get_gemini_model() -> GenerativeModel:
    """
    Initialize Gemini 1.5 Flash for trade analysis.
    
    Uses environment variables for project/location config.
    """
    project_id = "your-project-id"  # Should be loaded from env
    location = "us-central1"
    
    try:
        vertexai.init(project=project_id, location=location)
        return GenerativeModel("gemini-1.5-flash")
    except Exception as e:
        logger.error(f"Failed to initialize Gemini: {e}")
        raise


def _build_trade_analysis_prompt(
    trade_data: Dict[str, Any],
    market_regime: Optional[str] = None
) -> str:
    """
    Build prompt for Gemini to analyze a closed trade.
    
    Args:
        trade_data: Trade data from shadowTradeHistory
        market_regime: GEX regime at trade entry/exit (e.g., "LONG_GAMMA")
        
    Returns:
        Formatted prompt for Gemini
    """
    symbol = trade_data.get("symbol", "N/A")
    side = trade_data.get("side", "BUY")
    entry_price = trade_data.get("entry_price", "0")
    exit_price = trade_data.get("exit_price", "0")
    pnl = trade_data.get("realized_pnl", "0")
    quantity = trade_data.get("quantity", "0")
    reasoning = trade_data.get("reasoning", "No reasoning provided")
    
    # Calculate hold time if timestamps available
    created_at = trade_data.get("created_at")
    closed_at = trade_data.get("closed_at")
    hold_time_str = "Unknown"
    
    if created_at and closed_at:
        try:
            # Handle Firestore timestamps
            if hasattr(created_at, 'timestamp'):
                created_dt = datetime.fromtimestamp(created_at.timestamp())
            else:
                created_dt = created_at
                
            if hasattr(closed_at, 'timestamp'):
                closed_dt = datetime.fromtimestamp(closed_at.timestamp())
            else:
                closed_dt = closed_at
                
            duration = closed_dt - created_dt
            hours = duration.total_seconds() / 3600
            
            if hours < 1:
                hold_time_str = f"{int(duration.total_seconds() / 60)} minutes"
            elif hours < 24:
                hold_time_str = f"{hours:.1f} hours"
            else:
                hold_time_str = f"{hours / 24:.1f} days"
        except Exception as e:
            logger.warning(f"Failed to calculate hold time: {e}")
    
    regime_context = f"Market Regime (GEX): {market_regime}" if market_regime else "Market regime data not available"
    
    prompt = f"""Analyze this completed trade and provide actionable quant feedback.

## Trade Details
- **Symbol**: {symbol}
- **Side**: {side}
- **Quantity**: {quantity} shares
- **Entry Price**: ${entry_price}
- **Exit Price**: ${exit_price}
- **Realized P&L**: ${pnl}
- **Hold Time**: {hold_time_str}
- **Strategy Reasoning**: {reasoning}

## Market Context
{regime_context}

## Your Task
You are a quantitative trading analyst. Analyze this trade and provide:

1. **Exit Quality Grade** (A-F): Was the exit timing optimal?
2. **3 Actionable Quant Tips**: Specific, data-driven improvements for future trades
3. **GEX Context Analysis**: How did the market regime affect this trade?
4. **Risk Assessment**: Was position sizing appropriate given the regime?

Keep your response concise (under 200 words) but highly actionable. Focus on quantitative insights, not generic advice.

Format your response as:

**Grade**: [Letter Grade]

**Analysis**: [2-3 sentences on exit timing and P&L quality]

**Quant Tips**:
1. [Specific tip with numbers/thresholds]
2. [Specific tip with numbers/thresholds]
3. [Specific tip with numbers/thresholds]

**Regime Impact**: [How GEX affected the trade outcome]
"""
    
    return prompt


@firestore_fn.on_document_updated(
    document="shadowTradeHistory/{tradeId}",
    region="us-central1",
)
def on_trade_closed(event: firestore_fn.Event[firestore_fn.Change]) -> None:
    """
    Firestore trigger: Analyze trade when status changes to CLOSED.
    
    Triggered on: shadowTradeHistory/{tradeId} updates where status == 'CLOSED'
    
    Flow:
    1. Detect status change from OPEN -> CLOSED
    2. Fetch market regime at trade timestamp
    3. Send trade data to Gemini 1.5 Flash for analysis
    4. Store AI feedback in users/{uid}/tradeJournal/{tradeId}
    
    Args:
        event: Firestore document change event
    """
    try:
        # Get before and after snapshots
        before_data = event.data.before.to_dict() if event.data.before else {}
        after_data = event.data.after.to_dict() if event.data.after else {}
        
        # Check if status changed to CLOSED
        before_status = before_data.get("status", "")
        after_status = after_data.get("status", "")
        
        if before_status == after_status or after_status != "CLOSED":
            logger.info(f"Trade {event.params['tradeId']}: Status not changed to CLOSED, skipping")
            return
        
        logger.info(f"🔍 Analyzing closed trade: {event.params['tradeId']}")
        
        # Get trade data
        trade_id = event.params["tradeId"]
        trade_data = after_data
        user_id = trade_data.get("uid")
        
        if not user_id:
            logger.warning(f"Trade {trade_id} missing user ID, skipping analysis")
            return
        
        # Get Firestore client
        db = firestore.client()
        
        # Fetch market regime at trade entry time
        market_regime = None
        try:
            regime_doc = db.collection("systemStatus").document("market_regime").get()
            if regime_doc.exists:
                regime_data = regime_doc.to_dict()
                market_regime = regime_data.get("market_volatility_bias") or regime_data.get("regime")
        except Exception as regime_error:
            logger.warning(f"Failed to fetch market regime: {regime_error}")
        
        # Build prompt for Gemini
        prompt = _build_trade_analysis_prompt(trade_data, market_regime)
        
        # Get Gemini model
        try:
            model = _get_gemini_model()
        except Exception as model_error:
            logger.error(f"Failed to initialize Gemini: {model_error}")
            # Store error in journal
            journal_ref = (
                db.collection("users")
                .document(user_id)
                .collection("tradeJournal")
                .document(trade_id)
            )
            journal_ref.set({
                "trade_id": trade_id,
                "error": "AI analysis unavailable",
                "error_detail": str(model_error),
                "timestamp": firestore.SERVER_TIMESTAMP,
            })
            return
        
        # Generate AI analysis
        try:
            logger.info(f"Sending trade {trade_id} to Gemini for analysis...")
            response = model.generate_content(prompt)
            ai_feedback = response.text
            
            logger.info(f"✅ Received AI analysis for trade {trade_id}")
            
            # Parse grade from response (simple regex)
            import re
            grade_match = re.search(r'\*\*Grade\*\*:\s*([A-F][+-]?)', ai_feedback)
            quant_grade = grade_match.group(1) if grade_match else "N/A"
            
            # Store in tradeJournal
            journal_entry = {
                "trade_id": trade_id,
                "user_id": user_id,
                "symbol": trade_data.get("symbol"),
                "side": trade_data.get("side"),
                "entry_price": trade_data.get("entry_price"),
                "exit_price": trade_data.get("exit_price"),
                "realized_pnl": trade_data.get("realized_pnl", "0"),
                "quantity": trade_data.get("quantity"),
                "quant_grade": quant_grade,
                "ai_feedback": ai_feedback,
                "market_regime": market_regime,
                "created_at": trade_data.get("created_at"),
                "closed_at": trade_data.get("closed_at"),
                "analyzed_at": firestore.SERVER_TIMESTAMP,
            }
            
            journal_ref = (
                db.collection("users")
                .document(user_id)
                .collection("tradeJournal")
                .document(trade_id)
            )
            journal_ref.set(journal_entry, merge=True)
            
            logger.info(
                f"💾 Saved AI journal entry for trade {trade_id} "
                f"(Grade: {quant_grade})"
            )
            
        except Exception as ai_error:
            logger.exception(f"Error generating AI analysis: {ai_error}")
            
            # Store error in journal
            journal_ref = (
                db.collection("users")
                .document(user_id)
                .collection("tradeJournal")
                .document(trade_id)
            )
            journal_ref.set({
                "trade_id": trade_id,
                "error": "AI analysis failed",
                "error_detail": str(ai_error),
                "timestamp": firestore.SERVER_TIMESTAMP,
            })
    
    except Exception as e:
        logger.exception(f"Critical error in trade journal trigger: {e}")
        # Don't raise - we don't want to fail the entire Cloud Function


def close_shadow_trade(
    db: firestore.Client,
    trade_id: str,
    exit_price: str,
    exit_reason: str = "Manual close"
) -> Dict[str, Any]:
    """
    Helper function to close a shadow trade and trigger journal analysis.
    
    This function should be called by the execution engine or user action.
    The Firestore trigger (on_trade_closed) will automatically run AI analysis.
    
    Args:
        db: Firestore client
        trade_id: Trade ID to close
        exit_price: Exit price as string (Decimal precision)
        exit_reason: Reason for closing (e.g., "Take profit", "Stop loss")
        
    Returns:
        Updated trade document
    """
    try:
        trade_ref = db.collection("shadowTradeHistory").document(trade_id)
        trade_doc = trade_ref.get()
        
        if not trade_doc.exists:
            raise ValueError(f"Trade {trade_id} not found")
        
        trade_data = trade_doc.to_dict()
        
        if trade_data.get("status") == "CLOSED":
            logger.warning(f"Trade {trade_id} already closed")
            return trade_data
        
        # Calculate realized P&L using Decimal
        entry_price = Decimal(str(trade_data.get("entry_price", "0")))
        exit_price_decimal = Decimal(str(exit_price))
        quantity = Decimal(str(trade_data.get("quantity", "0")))
        side = trade_data.get("side", "BUY").upper()
        
        if side == "BUY":
            realized_pnl = (exit_price_decimal - entry_price) * quantity
        else:  # SELL
            realized_pnl = (entry_price - exit_price_decimal) * quantity
        
        # Update trade document
        update_data = {
            "status": "CLOSED",
            "exit_price": str(exit_price),
            "exit_reason": exit_reason,
            "realized_pnl": str(realized_pnl),
            "closed_at": firestore.SERVER_TIMESTAMP,
        }
        
        trade_ref.update(update_data)
        
        logger.info(
            f"Closed shadow trade {trade_id}: "
            f"{trade_data.get('symbol')} @ ${exit_price}, "
            f"P&L: ${realized_pnl}"
        )
        
        # Return updated data (trigger will handle AI analysis)
        return {**trade_data, **update_data}
        
    except Exception as e:
        logger.exception(f"Error closing shadow trade {trade_id}: {e}")
        raise
