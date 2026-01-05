"""
Institutional Analytics API endpoints for advanced trading analytics.

Features:
- GEX (Gamma Exposure) visualization data
- Sentiment scoring heatmap
- Execution audit with slippage analysis
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from backend.tenancy.auth import get_tenant_context
from backend.ledger.firestore import ledger_trades_collection

router = APIRouter(prefix="/api/institutional", tags=["institutional"])


# ============================================================================
# Response Models
# ============================================================================

class GEXDataPoint(BaseModel):
    """GEX data for a single strike price"""
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float
    open_interest_calls: int
    open_interest_puts: int


class GEXVisualization(BaseModel):
    """Complete GEX visualization data for a symbol"""
    symbol: str
    spot_price: float
    net_gex: float
    call_gex_total: float
    put_gex_total: float
    regime: str  # LONG_GAMMA, SHORT_GAMMA, NEUTRAL
    regime_description: str
    strikes: List[GEXDataPoint]
    call_wall: Optional[float]  # Strike with highest call OI
    put_wall: Optional[float]  # Strike with highest put OI
    timestamp: str
    strikes_analyzed: int


class SentimentScore(BaseModel):
    """Sentiment score for a single ticker"""
    symbol: str
    sentiment_score: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    action: str  # BUY, SELL, HOLD
    reasoning: str
    cash_flow_impact: str
    news_count: int
    last_analyzed: str
    color: str  # Hex color for heatmap


class SentimentHeatmap(BaseModel):
    """Collection of sentiment scores for multiple tickers"""
    tickers: List[SentimentScore]
    timestamp: str
    total_analyzed: int


class ExecutionAuditEntry(BaseModel):
    """Single execution audit record with slippage"""
    trade_id: str
    timestamp: str
    symbol: str
    side: str
    quantity: float
    intended_price: Optional[float]
    executed_price: float
    slippage_dollars: float
    slippage_bps: float  # Basis points
    slippage_percent: float
    order_type: str
    time_to_fill_ms: Optional[float]
    strategy_id: str
    status: str


class ExecutionAudit(BaseModel):
    """Execution audit summary with slippage analysis"""
    executions: List[ExecutionAuditEntry]
    total_executions: int
    avg_slippage_bps: float
    median_slippage_bps: float
    worst_slippage_bps: float
    best_slippage_bps: float
    total_slippage_cost: float
    avg_time_to_fill_ms: float
    timestamp: str


# ============================================================================
# Utility Functions
# ============================================================================

def get_tenant_id_from_header(tenant_id: Optional[str] = Query(None)) -> str:
    """Extract tenant ID from query parameter"""
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id query parameter required")
    return tenant_id


def calculate_slippage(intended_price: Optional[float], executed_price: float, side: str) -> Dict[str, float]:
    """
    Calculate slippage metrics.
    
    Slippage = Executed Price - Intended Price (for buys, negative is good)
    For sells, we flip the sign (selling higher than intended is good)
    """
    if intended_price is None or intended_price == 0:
        return {
            "slippage_dollars": 0.0,
            "slippage_bps": 0.0,
            "slippage_percent": 0.0
        }
    
    # Calculate raw slippage
    if side.lower() == "buy":
        slippage_dollars = executed_price - intended_price
    else:  # sell
        slippage_dollars = intended_price - executed_price
    
    # Calculate percentage and basis points
    slippage_percent = (slippage_dollars / intended_price) * 100
    slippage_bps = slippage_percent * 100  # Convert to basis points
    
    return {
        "slippage_dollars": round(slippage_dollars, 4),
        "slippage_bps": round(slippage_bps, 2),
        "slippage_percent": round(slippage_percent, 4)
    }


def get_sentiment_color(sentiment_score: float, confidence: float) -> str:
    """
    Get color for sentiment heatmap based on score and confidence.
    
    Color scale:
    - Strong positive (>0.5): Green shades
    - Neutral (-0.5 to 0.5): Yellow/Orange shades
    - Strong negative (<-0.5): Red shades
    - Low confidence: Desaturated
    """
    # Normalize confidence to affect saturation
    saturation = int(50 + (confidence * 50))  # 50-100%
    
    if sentiment_score > 0.7:
        return f"hsl(120, {saturation}%, 40%)"  # Dark green
    elif sentiment_score > 0.3:
        return f"hsl(120, {saturation}%, 60%)"  # Light green
    elif sentiment_score > -0.3:
        return f"hsl(45, {saturation}%, 60%)"  # Yellow
    elif sentiment_score > -0.7:
        return f"hsl(25, {saturation}%, 55%)"  # Orange
    else:
        return f"hsl(0, {saturation}%, 45%)"  # Red


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/gex/{symbol}", response_model=GEXVisualization)
async def get_gex_visualization(
    symbol: str,
    tenant_id: str = Depends(get_tenant_id_from_header),
):
    """
    Get real-time GEX (Gamma Exposure) visualization data for a symbol.
    
    This endpoint calculates gamma walls and market regime for institutional-grade
    options analysis.
    """
    try:
        # Import GEX engine (lazy import to avoid circular dependencies)
        from functions.utils.gex_engine import calculate_net_gex, get_regime_description
        
        # Calculate GEX
        gex_result = calculate_net_gex(symbol)
        
        # For now, we'll create mock strike-level data
        # In production, you'd store and retrieve actual strike-by-strike GEX
        spot = float(gex_result.spot_price)
        strikes_data = []
        
        # Generate strikes around spot (±10% in 1% increments)
        for i in range(-10, 11):
            strike = round(spot * (1 + i * 0.01), 2)
            
            # Mock strike-level data (in production, fetch from GEX calculation)
            call_gex = float(gex_result.call_gex) * (0.1 if abs(i) < 3 else 0.05)
            put_gex = abs(float(gex_result.put_gex)) * (0.1 if abs(i) < 3 else 0.05)
            
            strikes_data.append(GEXDataPoint(
                strike=strike,
                call_gex=call_gex,
                put_gex=-put_gex,  # Negative for puts
                net_gex=call_gex - put_gex,
                open_interest_calls=int(call_gex / (spot * 100)) if call_gex > 0 else 0,
                open_interest_puts=int(put_gex / (spot * 100)) if put_gex > 0 else 0,
            ))
        
        # Find gamma walls (strikes with highest OI)
        call_wall = max(strikes_data, key=lambda x: x.open_interest_calls).strike
        put_wall = max(strikes_data, key=lambda x: x.open_interest_puts).strike
        
        return GEXVisualization(
            symbol=gex_result.symbol,
            spot_price=float(gex_result.spot_price),
            net_gex=float(gex_result.net_gex),
            call_gex_total=float(gex_result.call_gex),
            put_gex_total=float(gex_result.put_gex),
            regime=gex_result.regime.value,
            regime_description=get_regime_description(gex_result.regime),
            strikes=strikes_data,
            call_wall=call_wall,
            put_wall=put_wall,
            timestamp=gex_result.timestamp.isoformat(),
            strikes_analyzed=gex_result.strikes_analyzed,
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to calculate GEX for {symbol}: {str(e)}"
        )


@router.get("/sentiment/heatmap", response_model=SentimentHeatmap)
async def get_sentiment_heatmap(
    tenant_id: str = Depends(get_tenant_id_from_header),
    symbols: Optional[str] = Query(None, description="Comma-separated list of symbols"),
):
    """
    Get sentiment heatmap data for multiple tickers analyzed by Gemini 1.5 Flash.
    
    Returns color-coded sentiment scores with confidence levels.
    """
    try:
        # Parse symbols
        symbol_list = symbols.split(",") if symbols else ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]
        
        # In production, fetch actual sentiment data from Firestore
        # For now, we'll create mock data based on the sentiment strategy structure
        from backend.ledger.firestore import get_firestore_client
        
        db = get_firestore_client()
        sentiment_scores = []
        
        for symbol in symbol_list:
            # Query latest sentiment analysis from Firestore
            # Collection: tenants/{tenant_id}/sentiment_analyses
            sentiment_ref = (
                db.collection("tenants")
                .document(tenant_id)
                .collection("sentiment_analyses")
                .where("symbol", "==", symbol)
                .order_by("analyzed_at", direction="DESCENDING")
                .limit(1)
            )
            
            docs = list(sentiment_ref.stream())
            
            if docs:
                data = docs[0].to_dict()
                sentiment_score = data.get("sentiment_score", 0.0)
                confidence = data.get("confidence", 0.0)
                
                sentiment_scores.append(SentimentScore(
                    symbol=symbol,
                    sentiment_score=sentiment_score,
                    confidence=confidence,
                    action=data.get("llm_action", "HOLD"),
                    reasoning=data.get("llm_reasoning", "No analysis available"),
                    cash_flow_impact=data.get("cash_flow_impact", "Unknown"),
                    news_count=data.get("news_count", 0),
                    last_analyzed=data.get("analyzed_at", datetime.now(timezone.utc).isoformat()),
                    color=get_sentiment_color(sentiment_score, confidence),
                ))
            else:
                # No data available - neutral score
                sentiment_scores.append(SentimentScore(
                    symbol=symbol,
                    sentiment_score=0.0,
                    confidence=0.0,
                    action="HOLD",
                    reasoning="No recent sentiment analysis available",
                    cash_flow_impact="Unknown",
                    news_count=0,
                    last_analyzed=datetime.now(timezone.utc).isoformat(),
                    color=get_sentiment_color(0.0, 0.0),
                ))
        
        return SentimentHeatmap(
            tickers=sentiment_scores,
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_analyzed=len(sentiment_scores),
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch sentiment heatmap: {str(e)}"
        )


@router.get("/execution/audit", response_model=ExecutionAudit)
async def get_execution_audit(
    tenant_id: str = Depends(get_tenant_id_from_header),
    days: int = Query(7, ge=1, le=90, description="Number of days to analyze"),
    symbol: Optional[str] = Query(None, description="Filter by symbol"),
):
    """
    Get execution audit with slippage analysis.
    
    Shows the difference between intended price and actual fill price for each trade,
    which is critical for understanding execution quality.
    """
    try:
        # Fetch trades from Firestore
        trades_ref = ledger_trades_collection(tenant_id=tenant_id)
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        # Build query
        query = trades_ref.where("ts", ">=", start_date)
        if symbol:
            query = query.where("symbol", "==", symbol)
        
        docs = query.order_by("ts", direction="DESCENDING").limit(500).stream()
        
        executions = []
        slippage_values = []
        fill_times = []
        
        for doc in docs:
            data = doc.to_dict()
            
            # Get prices
            intended_price = data.get("intended_price") or data.get("limit_price")
            executed_price = float(data.get("price", 0))
            side = data.get("side", "buy")
            
            # Calculate slippage
            slippage = calculate_slippage(intended_price, executed_price, side)
            
            # Parse timestamp
            ts = data.get("ts")
            if hasattr(ts, 'to_datetime'):
                ts = ts.to_datetime()
            elif isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            else:
                ts = datetime.now(timezone.utc)
            
            # Time to fill (if available)
            time_to_fill = data.get("time_to_fill_ms")
            if time_to_fill:
                fill_times.append(time_to_fill)
            
            # Create audit entry
            executions.append(ExecutionAuditEntry(
                trade_id=doc.id,
                timestamp=ts.isoformat(),
                symbol=data.get("symbol", ""),
                side=side,
                quantity=float(data.get("qty", 0)),
                intended_price=intended_price,
                executed_price=executed_price,
                slippage_dollars=slippage["slippage_dollars"],
                slippage_bps=slippage["slippage_bps"],
                slippage_percent=slippage["slippage_percent"],
                order_type=data.get("order_type", "market"),
                time_to_fill_ms=time_to_fill,
                strategy_id=data.get("strategy_id", ""),
                status=data.get("status", "filled"),
            ))
            
            slippage_values.append(slippage["slippage_bps"])
        
        # Calculate summary statistics
        if slippage_values:
            avg_slippage = sum(slippage_values) / len(slippage_values)
            sorted_slippage = sorted(slippage_values)
            median_slippage = sorted_slippage[len(sorted_slippage) // 2]
            worst_slippage = max(slippage_values)
            best_slippage = min(slippage_values)
            
            # Total slippage cost in dollars
            total_cost = sum(e.slippage_dollars * e.quantity for e in executions)
        else:
            avg_slippage = median_slippage = worst_slippage = best_slippage = total_cost = 0.0
        
        avg_fill_time = sum(fill_times) / len(fill_times) if fill_times else 0.0
        
        return ExecutionAudit(
            executions=executions,
            total_executions=len(executions),
            avg_slippage_bps=round(avg_slippage, 2),
            median_slippage_bps=round(median_slippage, 2),
            worst_slippage_bps=round(worst_slippage, 2),
            best_slippage_bps=round(best_slippage, 2),
            total_slippage_cost=round(total_cost, 2),
            avg_time_to_fill_ms=round(avg_fill_time, 2),
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate execution audit: {str(e)}"
        )


@router.post("/sentiment/analyze/{symbol}")
async def trigger_sentiment_analysis(
    symbol: str,
    tenant_id: str = Depends(get_tenant_id_from_header),
):
    """
    Trigger on-demand sentiment analysis for a symbol using Gemini 1.5 Flash.
    
    This will fetch recent news and run the LLM sentiment strategy.
    """
    try:
        from backend.strategy_engine.strategies.llm_sentiment_alpha import (
            make_decision,
            NewsItem,
        )
        from backend.ledger.firestore import get_firestore_client
        
        # Fetch recent news for this symbol
        db = get_firestore_client()
        news_ref = (
            db.collection("tenants")
            .document(tenant_id)
            .collection("news")
            .where("symbol", "==", symbol)
            .order_by("timestamp", direction="DESCENDING")
            .limit(10)
        )
        
        news_items = []
        for doc in news_ref.stream():
            data = doc.to_dict()
            news_items.append(NewsItem(
                headline=data.get("headline", ""),
                source=data.get("source", ""),
                timestamp=data.get("timestamp", datetime.now(timezone.utc)),
                symbol=symbol,
                url=data.get("url"),
                summary=data.get("summary"),
            ))
        
        # Analyze sentiment
        decision = make_decision(news_items, symbol)
        
        # Store result in Firestore
        sentiment_data = {
            "symbol": symbol,
            "sentiment_score": decision["signal_payload"].get("sentiment_score", 0.0),
            "confidence": decision["signal_payload"].get("confidence", 0.0),
            "llm_action": decision["signal_payload"].get("llm_action", "HOLD"),
            "llm_reasoning": decision["signal_payload"].get("llm_reasoning", ""),
            "cash_flow_impact": decision["signal_payload"].get("cash_flow_impact", ""),
            "news_count": decision["signal_payload"].get("news_count", 0),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }
        
        db.collection("tenants").document(tenant_id).collection("sentiment_analyses").add(
            sentiment_data
        )
        
        return {
            "success": True,
            "symbol": symbol,
            "sentiment": sentiment_data,
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze sentiment for {symbol}: {str(e)}"
        )
