"""
LLM-Enhanced Sentiment Strategy

Uses Gemini 1.5 Flash to analyze news headlines and generate trading signals
based on reasoning-driven sentiment analysis focused on future cash flow impact.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from backend.common.a2a_sdk import RiskAgentClient
from backend.contracts.risk import TradeCheckRequest

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """Represents a news article/headline"""
    headline: str
    source: str
    timestamp: datetime
    symbol: str
    url: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class SentimentAnalysis:
    """Result of LLM sentiment analysis"""
    sentiment_score: float  # -1.0 to 1.0
    confidence: float  # 0.0 to 1.0
    reasoning: str
    cash_flow_impact: str
    action: str  # BUY, SELL, HOLD
    target_symbols: List[str]


def _build_sentiment_prompt(news_items: List[NewsItem], symbol: str) -> str:
    """
    Build a comprehensive prompt for Gemini to analyze news sentiment
    with focus on future cash flow impact.
    """
    news_text = "\n\n".join([
        f"Headline: {item.headline}\n"
        f"Source: {item.source}\n"
        f"Time: {item.timestamp.isoformat()}\n"
        f"Symbol: {item.symbol}"
        + (f"\nSummary: {item.summary}" if item.summary else "")
        for item in news_items
    ])
    
    prompt = f"""You are a financial analyst specializing in fundamental analysis and cash flow forecasting.

Analyze the following news headlines for {symbol} and determine the potential impact on future cash flows and business fundamentals.

NEWS HEADLINES:
{news_text}

ANALYSIS FRAMEWORK:
1. Cash Flow Impact: How will this news affect the company's future cash generation?
   - Revenue implications (demand, pricing power, market share)
   - Cost structure changes (efficiency, margins, COGS)
   - Capital requirements (capex, working capital)
   - Free cash flow trajectory

2. Business Fundamentals: What is the underlying business impact?
   - Competitive position
   - Growth prospects
   - Risk factors
   - Management quality signals

3. Time Horizon: When will this impact materialize?
   - Immediate (0-3 months)
   - Near-term (3-12 months)
   - Long-term (12+ months)

REQUIRED OUTPUT (JSON format):
{{
    "sentiment_score": <float between -1.0 (very negative) and 1.0 (very positive)>,
    "confidence": <float between 0.0 and 1.0 indicating confidence in analysis>,
    "reasoning": "<detailed explanation of your analysis, focusing on cash flow and business fundamentals>",
    "cash_flow_impact": "<specific assessment of how this news affects future cash flows>",
    "action": "<BUY, SELL, or HOLD>",
    "target_symbols": [<list of stock symbols mentioned in news>]
}}

Focus on material, actionable insights that would impact investment decisions. Don't just summarize headlines - provide deep analytical reasoning about business and financial implications.

Respond ONLY with the JSON object, no additional text.
"""
    return prompt


def analyze_sentiment_with_gemini(
    news_items: List[NewsItem],
    symbol: str,
    model_id: str = "gemini-1.5-flash"
) -> Optional[SentimentAnalysis]:
    """
    Use Gemini to perform reasoning-driven sentiment analysis on news.
    
    Args:
        news_items: List of news articles to analyze
        symbol: Stock symbol being analyzed
        model_id: Vertex AI model ID (default: gemini-1.5-flash)
    
    Returns:
        SentimentAnalysis object or None if analysis fails
    """
    if not news_items:
        logger.warning("No news items to analyze")
        return None
    
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel
        from backend.common.vertex_ai import load_vertex_ai_config
        
        # Initialize Vertex AI
        cfg = load_vertex_ai_config()
        if not cfg.project_id:
            logger.error("Vertex AI project_id not configured")
            return None
        
        vertexai.init(project=cfg.project_id, location=cfg.location)
        
        # Use the configured model ID, falling back to gemini-1.5-flash
        model_name = model_id if model_id else "gemini-1.5-flash"
        model = GenerativeModel(model_name)
        
        # Build prompt
        prompt = _build_sentiment_prompt(news_items, symbol)
        
        # Generate analysis
        logger.info(f"Requesting sentiment analysis from {model_name} for {symbol}")
        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": 0.3,  # Lower temperature for more consistent analysis
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 2048,
            }
        )
        
        # Parse response
        response_text = response.text.strip()
        logger.debug(f"Raw Gemini response: {response_text}")
        
        # Extract JSON from response (handle potential markdown code blocks)
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        elif "```" in response_text:
            json_start = response_text.find("```") + 3
            json_end = response_text.find("```", json_start)
            response_text = response_text[json_start:json_end].strip()
        
        analysis_data = json.loads(response_text)
        
        # Validate and create SentimentAnalysis object
        return SentimentAnalysis(
            sentiment_score=float(analysis_data["sentiment_score"]),
            confidence=float(analysis_data["confidence"]),
            reasoning=str(analysis_data["reasoning"]),
            cash_flow_impact=str(analysis_data["cash_flow_impact"]),
            action=str(analysis_data["action"]).upper(),
            target_symbols=analysis_data.get("target_symbols", [symbol])
        )
        
    except Exception as e:
        logger.exception(f"Failed to analyze sentiment with Gemini: {e}")
        return None


async def make_decision(
    news_items: List[NewsItem],
    symbol: str,
    sentiment_threshold: float = 0.7,
    confidence_threshold: float = 0.8,
    risk_agent_client: Optional[RiskAgentClient] = None
) -> Dict:
    """
    Make trading decision based on LLM sentiment analysis and risk check.
    
    Strategy Rules:
    - If sentiment_score > sentiment_threshold AND confidence > confidence_threshold: BUY
    - If sentiment_score < -sentiment_threshold AND confidence > confidence_threshold: SELL
    - Otherwise: HOLD
    
    Args:
        news_items: Recent news items to analyze
        symbol: Stock symbol to trade
        sentiment_threshold: Minimum absolute sentiment score (default 0.7)
        confidence_threshold: Minimum confidence level (default 0.8)
        risk_agent_client: Optional client for the Risk Agent service.
    
    Returns:
        Decision dict with action, reason, and signal_payload
    """
    if not news_items:
        return {
            "action": "flat",
            "reason": "No recent news data available for analysis.",
            "signal_payload": {
                "news_count": 0,
                "sentiment_score": 0.0,
                "confidence": 0.0
            }
        }
    
    # Perform Gemini sentiment analysis
    analysis = analyze_sentiment_with_gemini(news_items, symbol)
    
    if not analysis:
        return {
            "action": "flat",
            "reason": "Failed to perform sentiment analysis.",
            "signal_payload": {
                "news_count": len(news_items),
                "error": "Analysis failed"
            }
        }
    
    # Log the analysis
    logger.info(
        f"Sentiment Analysis for {symbol}: "
        f"score={analysis.sentiment_score:.2f}, "
        f"confidence={analysis.confidence:.2f}, "
        f"action={analysis.action}"
    )
    
    # Determine initial action based on strategy rules
    action = "flat"
    reason = analysis.reasoning
    
    if (analysis.sentiment_score > sentiment_threshold and 
        analysis.confidence > confidence_threshold):
        action = "buy"
        reason = (
            f"Strong positive sentiment (score: {analysis.sentiment_score:.2f}, "
            f"confidence: {analysis.confidence:.2f}). "
            f"Cash Flow Analysis: {analysis.cash_flow_impact} "
            f"Reasoning: {analysis.reasoning}"
        )
    elif (analysis.sentiment_score < -sentiment_threshold and 
          analysis.confidence > confidence_threshold):
        action = "sell"
        reason = (
            f"Strong negative sentiment (score: {analysis.sentiment_score:.2f}, "
            f"confidence: {analysis.confidence:.2f}). "
            f"Cash Flow Analysis: {analysis.cash_flow_impact} "
            f"Reasoning: {analysis.reasoning}"
        )
    else:
        reason = (
            f"Sentiment below threshold (score: {analysis.sentiment_score:.2f}, "
            f"confidence: {analysis.confidence:.2f}). "
            f"Reasoning: {analysis.reasoning}"
        )

    risk_checked = False
    risk_approved = None

    # Perform risk check only when:
    # - a trade action is proposed (buy/sell)
    # - and the caller provided a RiskAgentClient
    # - and required request context is available (no guessing/placeholder ids)
    if risk_agent_client and action in {"buy", "sell"}:
        broker_account_id = str(os.getenv("RISK_BROKER_ACCOUNT_ID") or "").strip()
        strategy_id = str(os.getenv("RISK_STRATEGY_ID") or "").strip()
        auth = str(os.getenv("RISK_AUTHORIZATION") or "").strip() or None
        notional = str(os.getenv("RISK_NOTIONAL_USD") or "1000.0").strip()

        if not broker_account_id or not strategy_id:
            # Fail-safe: do not assume tenant/broker identifiers.
            risk_checked = False
            risk_approved = False
            action = "flat"
            reason = "Risk check context missing (set RISK_BROKER_ACCOUNT_ID and RISK_STRATEGY_ID); refusing trade."
        else:
            try:
                req = TradeCheckRequest(
                    broker_account_id=broker_account_id,
                    strategy_id=strategy_id,
                    symbol=symbol,
                    notional=notional,
                    side=action,
                    current_open_positions=0,
                    current_trades_today=0,
                    current_day_loss="0.0",
                    current_day_drawdown="0.0",
                )
                res = await risk_agent_client.check_trade(req, authorization=auth)
                risk_checked = True
                risk_approved = bool(res.allowed)
                if not res.allowed:
                    action = "flat"
                    reason = f"Trade blocked by Risk Agent: {res.reason or 'unknown_reason'}"
            except httpx.HTTPError as e:
                logger.error("Risk check HTTP error: %s", e)
                risk_checked = True
                risk_approved = False
                action = "flat"  # fail-safe
                reason = f"Risk check failed (http_error): {e}"
            except Exception as e:
                logger.exception("Unexpected error during risk check: %s", e)
                risk_checked = True
                risk_approved = False
                action = "flat"  # fail-safe
                reason = f"Risk check failed (unexpected_error): {e}"
    
    return {
        "action": action,
        "size": 1,  # Default position size
        "reason": reason,
        "signal_payload": {
            "news_count": len(news_items),
            "sentiment_score": analysis.sentiment_score,
            "confidence": analysis.confidence,
            "cash_flow_impact": analysis.cash_flow_impact,
            "llm_reasoning": analysis.reasoning,
            "llm_action": analysis.action,
            "target_symbols": analysis.target_symbols,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "model_id": "gemini-1.5-flash",
            "risk_checked": bool(risk_checked),
            "risk_approved": risk_approved,
        }
    }
