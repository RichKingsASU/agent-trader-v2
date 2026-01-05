"""
Strategy modules for the strategy engine.

Available strategies:
- naive_flow_trend: Simple flow-based trend following
- llm_sentiment_alpha: LLM-enhanced sentiment analysis using Gemini
"""

from .llm_sentiment_alpha import (
    NewsItem,
    SentimentAnalysis,
    make_decision as make_sentiment_decision,
    analyze_sentiment_with_gemini
)

__all__ = [
    'NewsItem',
    'SentimentAnalysis',
    'make_sentiment_decision',
    'analyze_sentiment_with_gemini',
]
