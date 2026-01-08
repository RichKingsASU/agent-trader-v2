"""
News Fetcher for Alpaca News API

Provides utilities to fetch and normalize news data from Alpaca's News API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
from alpaca.data.timeframe import TimeFrame

from backend.config.alpaca_env import load_alpaca_auth_env
from backend.strategy_engine.strategies.llm_sentiment_alpha import NewsItem

logger = logging.getLogger(__name__)


def fetch_recent_news(
    symbols: List[str],
    lookback_hours: int = 24,
    limit: int = 50
) -> List[NewsItem]:
    """
    Fetch recent news from Alpaca News API.
    
    Args:
        symbols: List of stock symbols to fetch news for
        lookback_hours: How many hours of news to fetch (default: 24)
        limit: Maximum number of news items to return (default: 50)
    
    Returns:
        List of NewsItem objects
    """
    try:
        # Get Alpaca credentials (APCA_* only; fail-fast)
        auth = load_alpaca_auth_env()
        
        # Initialize Alpaca News client
        news_client = NewsClient(api_key=auth.api_key_id, secret_key=auth.api_secret_key)
        
        # Calculate time range
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=lookback_hours)
        
        logger.info(
            f"Fetching news for {symbols} from {start_time.isoformat()} "
            f"to {end_time.isoformat()}"
        )
        
        # Build news request
        news_request = NewsRequest(
            symbols=symbols,
            start=start_time,
            end=end_time,
            limit=limit,
            sort="desc"  # Most recent first
        )
        
        # Fetch news
        news_set = news_client.get_news(news_request)
        
        # Convert to NewsItem objects
        news_items = []
        for article in news_set.data.values():
            # Each article is a News object from alpaca-py
            news_items.append(NewsItem(
                headline=article.headline,
                source=article.source if hasattr(article, 'source') else "Alpaca",
                timestamp=article.created_at if hasattr(article, 'created_at') else datetime.now(timezone.utc),
                symbol=article.symbols[0] if article.symbols else symbols[0],
                url=article.url if hasattr(article, 'url') else None,
                summary=article.summary if hasattr(article, 'summary') else None
            ))
        
        logger.info(f"Fetched {len(news_items)} news items for {symbols}")
        return news_items
        
    except Exception as e:
        logger.exception(f"Failed to fetch news from Alpaca: {e}")
        return []


def fetch_news_by_symbol(
    symbol: str,
    lookback_hours: int = 24,
    limit: int = 50
) -> List[NewsItem]:
    """
    Fetch recent news for a single symbol.
    
    Args:
        symbol: Stock symbol to fetch news for
        lookback_hours: How many hours of news to fetch (default: 24)
        limit: Maximum number of news items to return (default: 50)
    
    Returns:
        List of NewsItem objects
    """
    return fetch_recent_news([symbol], lookback_hours, limit)


def filter_news_by_relevance(
    news_items: List[NewsItem],
    min_headline_length: int = 20
) -> List[NewsItem]:
    """
    Filter news items to remove low-quality or irrelevant content.
    
    Args:
        news_items: List of news items to filter
        min_headline_length: Minimum headline length (default: 20 chars)
    
    Returns:
        Filtered list of NewsItem objects
    """
    filtered = []
    for item in news_items:
        # Filter out very short headlines (often noise)
        if len(item.headline) < min_headline_length:
            continue
        
        # Filter out common irrelevant patterns
        headline_lower = item.headline.lower()
        if any(skip_word in headline_lower for skip_word in [
            "sponsored",
            "advertisement",
            "ad:",
        ]):
            continue
        
        filtered.append(item)
    
    return filtered
