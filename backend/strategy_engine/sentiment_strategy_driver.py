#!/usr/bin/env python3
"""
LLM Sentiment Strategy Driver

Runs the LLM-Enhanced Sentiment strategy:
1. Fetches news headlines from Alpaca News API
2. Analyzes sentiment using Gemini 1.5 Flash
3. Generates trading signals based on sentiment thresholds
4. Logs signals to Firestore tradingSignals collection
5. Optionally executes paper trades

Usage:
    # Dry run (no trades)
    python -m backend.strategy_engine.sentiment_strategy_driver
    
    # Execute trades
    python -m backend.strategy_engine.sentiment_strategy_driver --execute
    
    # Custom symbols and thresholds
    STRATEGY_SYMBOLS=AAPL,MSFT,GOOGL python -m backend.strategy_engine.sentiment_strategy_driver
"""

import asyncio
import argparse
import logging
import sys
import os
from datetime import date, datetime, timezone, timedelta
from typing import List
from uuid import uuid4

from backend.strategy_engine.config import config
from backend.strategy_engine.news_fetcher import (
    fetch_news_by_symbol,
    filter_news_by_relevance
)
from backend.strategy_engine.strategies.llm_sentiment_alpha import make_decision
from backend.common.a2a_sdk import RiskAgentClient
from backend.strategy_engine.risk import (
    get_or_create_strategy_definition,
    log_decision,
)
from backend.strategy_engine.signal_writer import write_trading_signal
from backend.common.vertex_ai import init_vertex_ai_or_log
from backend.trading.proposals.emitter import emit_proposal
from backend.trading.proposals.models import (
    OrderProposal,
    ProposalAssetType,
    ProposalConstraints,
    ProposalRationale,
    ProposalSide,
)
from backend.risk.risk_allocator import allocate_risk

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def run_sentiment_strategy(
    symbols: List[str],
    execute: bool = False,
    sentiment_threshold: float = 0.7,
    confidence_threshold: float = 0.8,
    news_lookback_hours: int = 24
):
    """
    Main function to run the LLM sentiment strategy.
    
    Args:
        symbols: List of stock symbols to analyze
        execute: Whether to actually execute trades (default: False)
        sentiment_threshold: Minimum sentiment score for action (default: 0.7)
        confidence_threshold: Minimum confidence for action (default: 0.8)
        news_lookback_hours: How many hours of news to analyze (default: 24)
    """
    strategy_name = "llm_sentiment_alpha"
    today = date.today()
    correlation_id = os.getenv("CORRELATION_ID") or uuid4().hex
    repo_id = os.getenv("REPO_ID") or "RichKingsASU/agent-trader-v2"
    proposal_ttl_minutes = int(os.getenv("PROPOSAL_TTL_MINUTES") or "5")
    
    logger.info(f"=" * 80)
    logger.info(f"LLM Sentiment Strategy - {today}")
    logger.info(f"Symbols: {symbols}")
    logger.info(f"Execute trades: {execute}")
    logger.info(f"Sentiment threshold: {sentiment_threshold}")
    logger.info(f"Confidence threshold: {confidence_threshold}")
    logger.info(f"News lookback: {news_lookback_hours} hours")
    logger.info(f"=" * 80)
    
    # Initialize Vertex AI
    logger.info("Initializing Vertex AI...")
    if not init_vertex_ai_or_log():
        logger.error("Failed to initialize Vertex AI. Strategy cannot proceed.")
        return
    
    # Initialize Risk Agent Client
    RISK_SERVICE_URL = os.getenv("RISK_SERVICE_URL", "http://localhost:8002")
    risk_agent_client = RiskAgentClient(RISK_SERVICE_URL)
    logger.info(f"Initialized RiskAgentClient for URL: {RISK_SERVICE_URL}")
    
    # Get or create strategy definition
    strategy_id = await get_or_create_strategy_definition(strategy_name)
    logger.info(f"Strategy ID: {strategy_id}")
    
    # Process each symbol
    for symbol in symbols:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Processing symbol: {symbol}")
        logger.info(f"{'=' * 60}")
        
        try:
            # Step 1: Fetch news from Alpaca
            logger.info(f"Fetching news for {symbol} (last {news_lookback_hours} hours)...")
            news_items = fetch_news_by_symbol(
                symbol=symbol,
                lookback_hours=news_lookback_hours,
                limit=50
            )
            
            if not news_items:
                logger.warning(f"No news found for {symbol}")
                await log_decision(
                    strategy_id,
                    symbol,
                    "flat",
                    "No news available for analysis",
                    {"news_count": 0},
                    False
                )
                continue
            
            # Filter news for relevance
            filtered_news = filter_news_by_relevance(news_items)
            logger.info(
                f"Found {len(news_items)} news items, "
                f"{len(filtered_news)} after filtering"
            )
            
            if not filtered_news:
                logger.warning(f"No relevant news for {symbol}")
                await log_decision(
                    strategy_id,
                    symbol,
                    "flat",
                    "No relevant news after filtering",
                    {"news_count": len(news_items), "filtered_count": 0},
                    False
                )
                continue
            
            # Step 2: Analyze sentiment with Gemini AND perform risk check
            logger.info(f"Analyzing sentiment with Gemini 1.5 Flash and performing risk check...")
            decision = await make_decision(
                news_items=filtered_news,
                symbol=symbol,
                sentiment_threshold=sentiment_threshold,
                confidence_threshold=confidence_threshold,
                risk_agent_client=risk_agent_client
            )
            
            action = decision.get("action")
            reason = decision.get("reason")
            signal_payload = decision.get("signal_payload", {})
            
            # Log analysis results
            logger.info(f"\nSentiment Analysis Results:")
            logger.info(f"  Action: {action.upper()}")
            if "sentiment_score" in signal_payload:
                logger.info(f"  Sentiment Score: {signal_payload['sentiment_score']:.2f}")
            if "confidence" in signal_payload:
                logger.info(f"  Confidence: {signal_payload['confidence']:.2f}")
            if "cash_flow_impact" in signal_payload:
                logger.info(f"  Cash Flow Impact: {signal_payload['cash_flow_impact']}")
            if "llm_reasoning" in signal_payload:
                logger.info(f"\n  AI Reasoning:\n    {signal_payload['llm_reasoning']}")
            
            # Step 3: Write signal to Firestore
            logger.info(f"\nWriting signal to Firestore tradingSignals collection...")
            doc_id = write_trading_signal(
                strategy_id=strategy_id,
                strategy_name="LLM Sentiment Alpha",
                symbol=symbol,
                action=action,
                reason=reason,
                signal_payload=signal_payload,
                did_trade=False  # Will update if trade is executed
            )
            
            if doc_id:
                logger.info(f"Signal saved to Firestore: {doc_id}")
            else:
                logger.error("Failed to save signal to Firestore")
            
            # Step 4: Check if we should trade
            if action == "flat":
                logger.info(f"Decision: HOLD/FLAT - No action taken (possibly blocked by risk agent)")
                await log_decision(
                    strategy_id,
                    symbol,
                    "flat",
                    reason,
                    signal_payload,
                    False
                )
                continue
            
            # Canonical risk sizing (deterministic; no hidden globals inside allocator).
            # Preserve legacy behavior by using the existing $1000 request as the intent,
            # then constraining via portfolio-level caps if configured.
            daily_cap_pct = float(os.getenv("RISK_DAILY_CAP_PCT") or "1.0")
            max_strategy_pct = float(os.getenv("RISK_MAX_STRATEGY_ALLOCATION_PCT") or "1.0")
            daily_cap_pct = max(0.0, min(1.0, daily_cap_pct))
            max_strategy_pct = max(0.0, min(1.0, max_strategy_pct))

            notional = float(
                allocate_risk(
                    strategy_id="llm_sentiment_alpha",
                    signal_confidence=float(signal_payload.get("confidence") or 1.0),
                    market_state={
                        # This driver does not have buying power context; use the $1000 request
                        # with an explicit USD cap if desired via env.
                        "daily_risk_cap_usd": float(os.getenv("RISK_DAILY_CAP_USD") or "0") or 0.0,
                        "daily_risk_cap_pct": daily_cap_pct,
                        "max_strategy_allocation_pct": max_strategy_pct,
                        "current_allocations_usd": {},
                        "requested_notional_usd": 1000.0,  # legacy fixed size
                        "confidence_scaling": False,
                    },
                )
            )
            
            # The risk check is now handled within make_decision
            # We only proceed if action is not 'flat' (i.e., approved by risk)
            
            # Emit a non-executing, auditable proposal at the "would trade" decision point.
            side = ProposalSide.BUY if str(action).lower() == "buy" else ProposalSide.SELL
            created_at_utc = datetime.now(timezone.utc)
            proposal = OrderProposal(
                created_at_utc=created_at_utc,
                repo_id=repo_id,
                agent_name="strategy-engine",
                strategy_name=strategy_name,
                strategy_version=os.getenv("STRATEGY_VERSION") or None,
                correlation_id=correlation_id,
                symbol=symbol,
                asset_type=ProposalAssetType.EQUITY,
                option=None,
                side=side,
                quantity=1,
                limit_price=None,
                rationale=ProposalRationale(
                    short_reason=str(reason or "").strip() or "Strategy decision",
                    indicators=signal_payload or {},
                ),
                constraints=ProposalConstraints(
                    valid_until_utc=(created_at_utc + timedelta(minutes=max(1, proposal_ttl_minutes))),
                    requires_human_approval=True,
                ),
            )
            emit_proposal(proposal)

            # Step 5: Execute trade (if enabled)
            if execute:
                logger.info(f"\n{'*' * 60}")
                logger.info(f"EXECUTING {action.upper()} order for {symbol}")
                logger.info(f"{'*' * 60}")
                
                # TODO: Implement actual trade execution via Alpaca API
                # For now, just log the intent
                logger.info(f"Trade execution not yet implemented")
                logger.info(f"Would execute: {action.upper()} {symbol} (${notional:.2f})")
                
                await log_decision(
                    strategy_id,
                    symbol,
                    action,
                    reason,
                    signal_payload,
                    False
                )
                
                # Update Firestore signal with trade execution
                if doc_id:
                    logger.info(f"Updating signal {doc_id} to mark trade as executed")
                    # TODO: Update Firestore doc to set did_trade=True
            else:
                logger.info(f"\nDRY RUN MODE - No trade executed")
                logger.info(f"Would execute: {action.upper()} {symbol}")
                await log_decision(
                    strategy_id,
                    symbol,
                    action,
                    "Dry run mode - trade not executed",
                    signal_payload,
                    False
                )
            
        except Exception as e:
            logger.exception(f"Error processing {symbol}: {e}")
            await log_decision(
                strategy_id,
                symbol,
                "flat",
                f"Error during analysis: {str(e)}",
                {"error": str(e)},
                False
            )
            continue
    
    logger.info(f"\n{'=' * 80}")
    logger.info(f"Strategy run completed")
    logger.info(f"{'=' * 80}")


async def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Run the LLM Sentiment Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (no trades)
  python -m backend.strategy_engine.sentiment_strategy_driver
  
  # Execute trades
  python -m backend.strategy_engine.sentiment_strategy_driver --execute
  
  # Custom configuration via env vars
  STRATEGY_SYMBOLS=AAPL,NVDA,TSLA python -m backend.strategy_engine.sentiment_strategy_driver
        """
    )
    
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually place paper trades (default: dry run only)"
    )
    
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma-separated list of symbols (overrides STRATEGY_SYMBOLS env)"
    )
    
    parser.add_argument(
        "--sentiment-threshold",
        type=float,
        default=0.7,
        help="Minimum sentiment score for action (default: 0.7)"
    )
    
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.8,
        help="Minimum confidence for action (default: 0.8)"
    )
    
    parser.add_argument(
        "--news-lookback-hours",
        type=int,
        default=24,
        help="How many hours of news to analyze (default: 24)"
    )
    
    args = parser.parse_args()
    
    # Determine symbols to process
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",")]
    else:
        symbols = config.STRATEGY_SYMBOLS
    
    if not symbols:
        logger.error("No symbols specified. Set STRATEGY_SYMBOLS env var or use --symbols")
        sys.exit(1)
    
    # Run the strategy
    await run_sentiment_strategy(
        symbols=symbols,
        execute=args.execute,
        sentiment_threshold=args.sentiment_threshold,
        confidence_threshold=args.confidence_threshold,
        news_lookback_hours=args.news_lookback_hours
    )


if __name__ == "__main__":
    asyncio.run(main())
