#!/usr/bin/env python3
"""
Test script for LLM Sentiment Strategy

This script validates the key components of the sentiment strategy:
1. News fetching from Alpaca
2. Sentiment analysis with Gemini
3. Signal generation
4. Firestore writing

Usage:
    python -m backend.strategy_engine.test_sentiment_strategy
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_imports():
    """Test that all required modules can be imported"""
    logger.info("=" * 60)
    logger.info("TEST 1: Module Imports")
    logger.info("=" * 60)
    
    try:
        from backend.strategy_engine.news_fetcher import fetch_news_by_symbol
        logger.info("✓ news_fetcher imported successfully")
        
        from backend.strategy_engine.strategies.llm_sentiment_alpha import (
            make_decision,
            analyze_sentiment_with_gemini,
            NewsItem
        )
        logger.info("✓ llm_sentiment_alpha imported successfully")
        
        from backend.strategy_engine.signal_writer import write_trading_signal
        logger.info("✓ signal_writer imported successfully")
        
        from backend.common.vertex_ai import init_vertex_ai_or_log
        logger.info("✓ vertex_ai imported successfully")
        
        return True
    except Exception as e:
        logger.error(f"✗ Import failed: {e}")
        return False


def test_vertex_ai_init():
    """Test Vertex AI initialization"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Vertex AI Initialization")
    logger.info("=" * 60)
    
    try:
        from backend.common.vertex_ai import init_vertex_ai_or_log, load_vertex_ai_config
        
        cfg = load_vertex_ai_config()
        logger.info(f"Project ID: {cfg.project_id}")
        logger.info(f"Location: {cfg.location}")
        logger.info(f"Model ID: {cfg.model_id}")
        
        result = init_vertex_ai_or_log()
        if result:
            logger.info("✓ Vertex AI initialized successfully")
            return True
        else:
            logger.warning("✗ Vertex AI initialization failed (non-fatal)")
            return False
    except Exception as e:
        logger.error(f"✗ Vertex AI init error: {e}")
        return False


def test_news_fetching():
    """Test fetching news from Alpaca"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: News Fetching (Alpaca API)")
    logger.info("=" * 60)
    
    try:
        from backend.strategy_engine.news_fetcher import (
            fetch_news_by_symbol,
            filter_news_by_relevance
        )
        
        symbol = "SPY"
        logger.info(f"Fetching news for {symbol}...")
        
        news_items = fetch_news_by_symbol(symbol, lookback_hours=24, limit=10)
        logger.info(f"Fetched {len(news_items)} news items")
        
        if news_items:
            logger.info("\nSample news item:")
            item = news_items[0]
            logger.info(f"  Headline: {item.headline}")
            logger.info(f"  Source: {item.source}")
            logger.info(f"  Symbol: {item.symbol}")
            logger.info(f"  Timestamp: {item.timestamp}")
            
            # Test filtering
            filtered = filter_news_by_relevance(news_items)
            logger.info(f"\nAfter filtering: {len(filtered)} items")
            logger.info("✓ News fetching successful")
            return True, news_items
        else:
            logger.warning("✗ No news items fetched (may be normal if no recent news)")
            return False, []
            
    except Exception as e:
        logger.error(f"✗ News fetching failed: {e}")
        import traceback
        traceback.print_exc()
        return False, []


def test_sentiment_analysis(news_items):
    """Test sentiment analysis with Gemini"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Sentiment Analysis (Gemini)")
    logger.info("=" * 60)
    
    if not news_items:
        logger.warning("Skipping sentiment analysis (no news items)")
        return False
    
    try:
        from backend.strategy_engine.strategies.llm_sentiment_alpha import (
            analyze_sentiment_with_gemini,
            NewsItem
        )
        
        # Use first few items to reduce cost
        test_items = news_items[:3]
        symbol = test_items[0].symbol
        
        logger.info(f"Analyzing {len(test_items)} news items for {symbol}...")
        
        analysis = analyze_sentiment_with_gemini(test_items, symbol)
        
        if analysis:
            logger.info("\nAnalysis Results:")
            logger.info(f"  Sentiment Score: {analysis.sentiment_score:.2f}")
            logger.info(f"  Confidence: {analysis.confidence:.2f}")
            logger.info(f"  Action: {analysis.action}")
            logger.info(f"  Cash Flow Impact: {analysis.cash_flow_impact[:100]}...")
            logger.info(f"  Reasoning: {analysis.reasoning[:200]}...")
            logger.info("✓ Sentiment analysis successful")
            return True
        else:
            logger.error("✗ Sentiment analysis returned None")
            return False
            
    except Exception as e:
        logger.error(f"✗ Sentiment analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_decision_logic(news_items):
    """Test the complete decision-making logic"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 5: Decision Logic")
    logger.info("=" * 60)
    
    if not news_items:
        logger.warning("Skipping decision logic (no news items)")
        return False
    
    try:
        from backend.strategy_engine.strategies.llm_sentiment_alpha import make_decision
        
        symbol = news_items[0].symbol
        test_items = news_items[:3]
        
        logger.info(f"Making decision for {symbol} with {len(test_items)} news items...")
        
        decision = await make_decision(
            news_items=test_items,
            symbol=symbol,
            sentiment_threshold=0.7,
            confidence_threshold=0.8
        )
        
        logger.info("\nDecision Results:")
        logger.info(f"  Action: {decision['action']}")
        logger.info(f"  Reason: {decision['reason'][:200]}...")
        
        if "signal_payload" in decision:
            payload = decision["signal_payload"]
            if "sentiment_score" in payload:
                logger.info(f"  Sentiment Score: {payload['sentiment_score']:.2f}")
            if "confidence" in payload:
                logger.info(f"  Confidence: {payload['confidence']:.2f}")
        
        logger.info("✓ Decision logic successful")
        return True
        
    except Exception as e:
        logger.error(f"✗ Decision logic failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_firestore_write():
    """Test writing to Firestore tradingSignals collection"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 6: Firestore Write")
    logger.info("=" * 60)
    
    try:
        from backend.strategy_engine.signal_writer import write_trading_signal
        from uuid import uuid4
        
        # Create test signal
        test_strategy_id = uuid4()
        test_signal_payload = {
            "sentiment_score": 0.75,
            "confidence": 0.85,
            "llm_reasoning": "Test reasoning from sentiment strategy",
            "cash_flow_impact": "Test cash flow impact",
            "news_count": 5,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "model_id": "gemini-1.5-flash"
        }
        
        logger.info("Writing test signal to Firestore...")
        
        doc_id = write_trading_signal(
            strategy_id=test_strategy_id,
            strategy_name="LLM Sentiment Alpha (Test)",
            symbol="SPY",
            action="BUY",
            reason="Test signal from sentiment strategy validation",
            signal_payload=test_signal_payload,
            did_trade=False
        )
        
        if doc_id:
            logger.info(f"✓ Signal written successfully: {doc_id}")
            logger.info(f"  View in Firestore console: tradingSignals/{doc_id}")
            return True
        else:
            logger.error("✗ Signal write returned None")
            return False
            
    except Exception as e:
        logger.error(f"✗ Firestore write failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all tests and report results"""
    logger.info("\n" + "=" * 80)
    logger.info("LLM SENTIMENT STRATEGY - TEST SUITE")
    logger.info("=" * 80)
    
    results = {}
    
    # Test 1: Imports
    results["imports"] = test_imports()
    
    # Test 2: Vertex AI
    results["vertex_ai"] = test_vertex_ai_init()
    
    # Test 3: News Fetching
    news_success, news_items = test_news_fetching()
    results["news_fetching"] = news_success
    
    # Test 4: Sentiment Analysis (requires Vertex AI and news)
    if results["vertex_ai"] and news_items:
        results["sentiment_analysis"] = test_sentiment_analysis(news_items)
    else:
        logger.warning("\nSkipping sentiment analysis (missing prerequisites)")
        results["sentiment_analysis"] = None
    
    # Test 5: Decision Logic (requires news)
    if news_items:
        results["decision_logic"] = await test_decision_logic(news_items)
    else:
        logger.warning("\nSkipping decision logic (no news items)")
        results["decision_logic"] = None
    
    # Test 6: Firestore Write
    results["firestore_write"] = await test_firestore_write()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else ("⊘ SKIP" if result is None else "✗ FAIL")
        logger.info(f"{test_name.replace('_', ' ').title()}: {status}")
    
    # Overall result
    passed = sum(1 for r in results.values() if r is True)
    failed = sum(1 for r in results.values() if r is False)
    skipped = sum(1 for r in results.values() if r is None)
    
    logger.info(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
    
    if failed > 0:
        logger.error("\n⚠ Some tests failed. Please review errors above.")
        return False
    elif passed == 0:
        logger.warning("\n⚠ No tests passed. Please check configuration.")
        return False
    else:
        logger.info("\n✓ All critical tests passed!")
        return True


def main():
    """Main entry point"""
    try:
        success = asyncio.run(run_all_tests())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Test suite failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
