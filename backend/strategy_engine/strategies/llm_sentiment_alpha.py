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
from math import isfinite
from typing import Any, Dict, List, Optional, Tuple

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


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return int(default)
    try:
        return int(str(raw).strip())
    except Exception:
        return int(default)


def _normalize_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _allowed_sources() -> Optional[set[str]]:
    raw = os.getenv("STRATEGY_NEWS_ALLOWED_SOURCES")
    if raw is None or str(raw).strip() == "":
        return None
    parts = [p.strip() for p in str(raw).split(",")]
    allow = {p for p in parts if p}
    return allow or None


def _filter_and_summarize_news_inputs(
    news_items: List[NewsItem],
    *,
    now_utc: datetime,
    lookback_hours: Optional[int] = None,
) -> Tuple[List[NewsItem], Dict[str, Any]]:
    """
    Safety filter for news inputs used by the sentiment strategy.

    Fail-closed posture:
    - drop items with invalid timestamps
    - drop future-dated items beyond allowed skew
    - drop items older than the optional lookback window
    - drop items from disallowed sources (if allowlist configured)
    """
    max_future_skew_s = max(0.0, _env_float("STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS", 5.0))
    max_age_s = None
    if lookback_hours is not None:
        max_age_s = max(0.0, float(lookback_hours) * 3600.0)
    allow = _allowed_sources()

    dropped_invalid_ts = 0
    dropped_future = 0
    dropped_stale = 0
    dropped_source = 0
    kept: List[NewsItem] = []

    for it in news_items or []:
        ts = getattr(it, "timestamp", None)
        if not isinstance(ts, datetime):
            dropped_invalid_ts += 1
            continue
        tsu = _normalize_utc(ts)
        age_s = (now_utc - tsu).total_seconds()
        if age_s < -max_future_skew_s:
            dropped_future += 1
            continue
        if max_age_s is not None and age_s > max_age_s:
            dropped_stale += 1
            continue
        src = str(getattr(it, "source", "") or "").strip()
        if src == "":
            dropped_source += 1
            continue
        if allow is not None and src not in allow:
            dropped_source += 1
            continue
        # normalize timestamp/source back onto the object
        it.timestamp = tsu
        it.source = src
        kept.append(it)

    sources = sorted({it.source for it in kept if getattr(it, "source", None)})
    ts_list = [it.timestamp for it in kept]
    min_ts = min(ts_list).isoformat() if ts_list else None
    max_ts = max(ts_list).isoformat() if ts_list else None
    newest_age_s = (now_utc - max(ts_list)).total_seconds() if ts_list else None
    oldest_age_s = (now_utc - min(ts_list)).total_seconds() if ts_list else None

    summary: Dict[str, Any] = {
        "now_utc": now_utc.isoformat(),
        "lookback_hours": int(lookback_hours) if lookback_hours is not None else None,
        "allowed_sources": sorted(allow) if allow is not None else None,
        "kept_count": len(kept),
        "sources": sources,
        "time_window": {
            "min_timestamp_utc": min_ts,
            "max_timestamp_utc": max_ts,
            "newest_age_seconds": newest_age_s,
            "oldest_age_seconds": oldest_age_s,
            "max_future_skew_seconds": max_future_skew_s,
        },
        "dropped": {
            "invalid_timestamp": dropped_invalid_ts,
            "future_dated": dropped_future,
            "stale": dropped_stale,
            "disallowed_or_missing_source": dropped_source,
        },
    }
    return kept, summary


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _clamp11(x: float) -> float:
    if x < -1.0:
        return -1.0
    if x > 1.0:
        return 1.0
    return x


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
    news_lookback_hours: Optional[int] = None,
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
        news_lookback_hours: Optional lookback window for input timestamp validation

    Returns:
        Decision dict with action, reason, and signal_payload
    """
    now_utc = datetime.now(timezone.utc)
    stale_seconds = max(0.0, _env_float("STRATEGY_NEWS_STALE_SECONDS", 6 * 3600.0))
    min_items = max(1, _env_int("STRATEGY_NEWS_MIN_ITEMS", 1))
    # Optional extra lookback enforcement (driver may already filter, but strategy must be safe standalone).
    lookback_hours = int(news_lookback_hours) if news_lookback_hours is not None else None
    if lookback_hours is None:
        lookback_hours_env = os.getenv("STRATEGY_NEWS_LOOKBACK_HOURS")
        if lookback_hours_env is not None and str(lookback_hours_env).strip() != "":
            lookback_hours = _env_int("STRATEGY_NEWS_LOOKBACK_HOURS", 24)

    safe_news, news_summary = _filter_and_summarize_news_inputs(
        news_items or [],
        now_utc=now_utc,
        lookback_hours=lookback_hours,
    )

    newest_age_s = news_summary.get("time_window", {}).get("newest_age_seconds")
    blocked_reason: Optional[str] = None
    if len(safe_news) < min_items:
        blocked_reason = f"Insufficient valid news items (need >= {min_items})."
    elif newest_age_s is None:
        blocked_reason = "Missing timestamps after safety filtering."
    else:
        try:
            if float(newest_age_s) > stale_seconds:
                blocked_reason = (
                    f"Stale news (newest age {float(newest_age_s):.0f}s > {stale_seconds:.0f}s threshold)."
                )
        except Exception:
            blocked_reason = "Invalid timestamp ages after safety filtering."

    base_payload: Dict[str, Any] = {
        "strategy": "llm_sentiment_alpha",
        "symbol": symbol,
        "news_count": len(safe_news),
        "input_review": {"news": news_summary},
        "thresholds": {
            "sentiment_threshold": float(sentiment_threshold),
            "confidence_threshold": float(confidence_threshold),
            "stale_seconds": float(stale_seconds),
            "min_news_items": int(min_items),
        },
        "analyzed_at": now_utc.isoformat(),
        # Risk allocation happens centrally; strategies never self-authorize capital.
        "risk_checked": False,
    }

    if blocked_reason is not None:
        base_payload["safety"] = {
            "posture": "HOLD_FAIL_CLOSED",
            "blocked": True,
            "block_reason": blocked_reason,
            "no_trade_amplification": True,
        }
        base_payload["sentiment_score"] = 0.0
        base_payload["confidence"] = 0.0
        return {"action": "flat", "reason": blocked_reason, "signal_payload": base_payload}

    analysis = analyze_sentiment_with_gemini(safe_news, symbol)
    if not analysis:
        base_payload["safety"] = {
            "posture": "HOLD_FAIL_CLOSED",
            "blocked": True,
            "block_reason": "LLM sentiment analysis failed.",
            "no_trade_amplification": True,
        }
        base_payload["error"] = "analysis_failed"
        base_payload["sentiment_score"] = 0.0
        base_payload["confidence"] = 0.0
        return {"action": "flat", "reason": "Failed to perform sentiment analysis.", "signal_payload": base_payload}

    raw_score = float(analysis.sentiment_score)
    raw_conf = float(analysis.confidence)
    if not (isfinite(raw_score) and isfinite(raw_conf)):
        base_payload["safety"] = {
            "posture": "HOLD_FAIL_CLOSED",
            "blocked": True,
            "block_reason": "Non-finite sentiment outputs.",
            "no_trade_amplification": True,
        }
        base_payload["error"] = "non_finite_outputs"
        base_payload["sentiment_score"] = 0.0
        base_payload["confidence"] = 0.0
        return {"action": "flat", "reason": "Invalid sentiment outputs.", "signal_payload": base_payload}

    score = _clamp11(raw_score)
    conf = _clamp01(raw_conf)
    clamped = (score != raw_score) or (conf != raw_conf)

    # No trade amplification: never propagate confidence above thresholds/caps required to act.
    intent_conf_cap = _env_float("STRATEGY_MAX_INTENT_CONFIDENCE", float(confidence_threshold))
    safe_intent_conf = min(conf, float(confidence_threshold), float(intent_conf_cap))

    logger.info(
        "Sentiment Analysis for %s: score=%.2f (raw=%.2f), confidence=%.2f (raw=%.2f), action=%s",
        symbol,
        score,
        raw_score,
        conf,
        raw_conf,
        analysis.action,
    )

    action = "flat"
    reason = analysis.reasoning

    if (score > float(sentiment_threshold)) and (conf >= float(confidence_threshold)):
        action = "buy"
        reason = (
            f"Strong positive sentiment (score: {score:.2f}, "
            f"confidence: {conf:.2f}). "
            f"Cash Flow Analysis: {analysis.cash_flow_impact} "
            f"Reasoning: {analysis.reasoning}"
        )
    elif (score < -float(sentiment_threshold)) and (conf >= float(confidence_threshold)):
        action = "sell"
        reason = (
            f"Strong negative sentiment (score: {score:.2f}, "
            f"confidence: {conf:.2f}). "
            f"Cash Flow Analysis: {analysis.cash_flow_impact} "
            f"Reasoning: {analysis.reasoning}"
        )
    else:
        reason = (
            f"Sentiment below threshold (score: {score:.2f}, "
            f"confidence: {conf:.2f}). "
            f"Reasoning: {analysis.reasoning}"
        )

    base_payload.update(
        {
            "sentiment_score": score,
            "confidence": safe_intent_conf,
            "raw_confidence": conf,
            "raw_sentiment_score": raw_score,
            "output_clamped": bool(clamped),
            "cash_flow_impact": analysis.cash_flow_impact,
            "llm_reasoning": analysis.reasoning,
            "llm_action": analysis.action,
            "target_symbols": analysis.target_symbols,
            "model_id": os.getenv("VERTEX_MODEL_ID") or "gemini-1.5-flash",
            "safety": {
                "posture": "OBSERVE_SAFE",
                "blocked": action == "flat",
                "no_trade_amplification": True,
                "notes": "Strategy emits HOLD on missing/stale/future news and caps intent confidence.",
            },
            "explanation": {
                "summary": (
                    f"{symbol}: {action.upper()} based on sentiment {score:.2f} "
                    f"and confidence {conf:.2f} with {len(safe_news)} news items."
                ),
                "key_factors": [
                    {
                        "name": "sentiment_score",
                        "value": f"{score:.2f}",
                        "direction": "bullish" if score > 0 else "bearish" if score < 0 else "neutral",
                    },
                    {"name": "confidence", "value": f"{conf:.2f}"},
                    {"name": "news_count", "value": str(len(safe_news))},
                    {
                        "name": "newest_news_age_seconds",
                        "value": str(int(newest_age_s)) if newest_age_s is not None else None,
                    },
                ],
                "meta": {
                    "thresholds": base_payload.get("thresholds"),
                    "input_review": base_payload.get("input_review"),
                },
            },
        }
    )

    return {"action": action, "reason": reason, "signal_payload": base_payload}
