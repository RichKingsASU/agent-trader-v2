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
from backend.risk_allocator import RiskAllocator
from backend.trading.agent_intent.emitter import emit_agent_intent
from backend.trading.agent_intent.models import (
    AgentIntent,
    AgentIntentConstraints,
    AgentIntentRationale,
    IntentAssetType,
    IntentKind,
    IntentSide,
)
from backend.strategy_engine.risk import (
    get_or_create_strategy_definition,
    log_decision,
)
from backend.strategy_engine.signal_writer import write_trading_signal
from backend.common.vertex_ai import init_vertex_ai_or_log
from backend.trading.decision_flow import intent_to_order_proposal
from backend.trading.proposals.emitter import emit_proposal
from backend.common.ops_log import log_json
from backend.strategy_engine.daily_target_halt import DailyTargetHaltController

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _filter_by_timestamp_safety(news_items, *, lookback_hours: int):
    """
    Enforce event timestamp safety on news events (fail-closed-ish):
    - drop future-dated items beyond skew
    - drop items older than lookback window
    """
    now = datetime.now(timezone.utc)
    max_age_s = max(0.0, float(lookback_hours) * 3600.0)
    max_future_skew_s = max(0.0, _env_float("STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS", 5.0))
    out = []
    for it in news_items:
        ts = getattr(it, "timestamp", None)
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)
        age_s = (now - ts).total_seconds()
        if age_s < -max_future_skew_s:
            continue
        if age_s > max_age_s:
            continue
        out.append(it)
    return out


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
    tenant_id = (os.getenv("TENANT_ID") or "local").strip() or "local"
    uid = (os.getenv("USER_ID") or os.getenv("UID") or "").strip()
    daily_target = DailyTargetHaltController(
        strategy_name=strategy_name,
        tenant_id=tenant_id,
        uid=uid,
        log_fn=log_json,
    )
    
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
    
    allocator = RiskAllocator()
    
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

            # Timestamp safety gate: drop stale/future news items.
            safe_news = _filter_by_timestamp_safety(filtered_news, lookback_hours=news_lookback_hours)
            if len(safe_news) != len(filtered_news):
                logger.info(
                    "Dropped %d news items due to timestamp safety (stale/future)",
                    (len(filtered_news) - len(safe_news)),
                )
            filtered_news = safe_news
            
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
                news_lookback_hours=news_lookback_hours,
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
                correlation_id=correlation_id,
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

            # Strategy-local daily target halt (profit lock): stop emitting new intents once the daily return target is hit.
            if daily_target.should_halt(symbol=symbol, iteration_id=correlation_id):
                m = daily_target.last_metrics
                reason = "DAILY_TARGET_HALT: daily_return_pct >= 0.04 (stop emitting intents)"
                logger.warning(reason)
                try:
                    log_json(
                        intent_type="strategy_decision",
                        severity="WARNING",
                        symbol=symbol,
                        strategy=strategy_name,
                        action="flat",
                        reason=reason,
                        iteration_id=correlation_id,
                        blocked=True,
                        block_reason="daily_target_halt",
                        daily_return_pct=(float(m.daily_return_pct) if m is not None else None),
                        daily_target_pct=0.04,
                        current_equity_usd=(float(m.current_equity_usd) if m is not None else None),
                        starting_equity_usd=(float(m.starting_equity_usd) if m is not None else None),
                    )
                except Exception:
                    pass
                break
            
            created_at_utc = datetime.now(timezone.utc)
            side = (
                IntentSide.BUY
                if str(action).lower() == "buy"
                else IntentSide.SELL
                if str(action).lower() == "sell"
                else IntentSide.FLAT
            )
            intent = AgentIntent(
                created_at_utc=created_at_utc,
                repo_id=repo_id,
                agent_name="strategy-engine",
                strategy_name=strategy_name,
                strategy_version=os.getenv("STRATEGY_VERSION") or None,
                correlation_id=correlation_id,
                symbol=symbol,
                asset_type=IntentAssetType.EQUITY,
                option=None,
                kind=IntentKind.DIRECTIONAL,
                side=side,
                confidence=float(signal_payload.get("confidence")) if signal_payload.get("confidence") is not None else None,
                rationale=AgentIntentRationale(
                    short_reason=str(reason or "").strip() or "Strategy decision",
                    indicators=signal_payload or {},
                ),
                constraints=AgentIntentConstraints(
                    valid_until_utc=(created_at_utc + timedelta(minutes=max(1, proposal_ttl_minutes))),
                    requires_human_approval=True,
                    order_type="market",
                    time_in_force="day",
                    limit_price=None,
                    delta_to_hedge=None,
                ),
            )
            emit_agent_intent(intent)

            # Allocator owns sizing (qty/notional). This driver never picks quantity.
            allocation = allocator.allocate_without_gates(intent=intent, last_price=0.0)
            proposal = intent_to_order_proposal(intent=intent, quantity=int(allocation.qty))
            if proposal is not None:
                emit_proposal(proposal)

            # Step 5: Execute trade (if enabled)
            if execute:
                logger.info(f"\n{'*' * 60}")
                logger.info(f"EXECUTING {action.upper()} order for {symbol}")
                logger.info(f"{'*' * 60}")
                
                # TODO: Implement actual trade execution via Alpaca API
                # For now, just log the intent
                logger.info(f"Trade execution not yet implemented")
                logger.info(f"Would execute: {action.upper()} {symbol}")
                
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
