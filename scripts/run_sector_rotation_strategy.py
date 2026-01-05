#!/usr/bin/env python3
"""
Sector Rotation Strategy Runner

This script executes the Dynamic Sector Rotation Strategy with real market data.
It fetches sentiment scores from Firestore, evaluates the strategy, and optionally
executes trades via the Alpaca API.

Usage:
    # Dry run (no trades)
    python scripts/run_sector_rotation_strategy.py
    
    # Execute trades
    python scripts/run_sector_rotation_strategy.py --execute
    
    # Custom configuration
    python scripts/run_sector_rotation_strategy.py --top-n 5 --allocation 0.70
    
    # Use specific tenant
    python scripts/run_sector_rotation_strategy.py --tenant-id your-tenant-id
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "functions"))

import firebase_admin
from firebase_admin import firestore

from strategies.sector_rotation import SectorRotationStrategy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def init_firebase() -> firestore.Client:
    """Initialize Firebase and return Firestore client."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return firestore.client()


async def fetch_sentiment_data(db: firestore.Client, tenant_id: str = None) -> Dict[str, Any]:
    """
    Fetch latest sentiment scores from Firestore tradingSignals collection.
    
    Args:
        db: Firestore client
        tenant_id: Optional tenant ID for multi-tenant setup
    
    Returns:
        Market data dictionary with sentiment scores
    """
    logger.info("Fetching sentiment data from Firestore...")
    
    # Query the latest sentiment signals (last 24 hours)
    query = db.collection('tradingSignals').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(200)
    
    # Apply tenant filter if provided
    if tenant_id:
        query = query.where('tenant_id', '==', tenant_id)
    
    docs = query.stream()
    
    # Build tickers data structure
    tickers_map = {}
    
    for doc in docs:
        data = doc.to_dict()
        symbol = data.get('symbol', '')
        
        # Skip if no symbol or sentiment
        if not symbol or 'sentiment_score' not in data:
            continue
        
        # Use most recent score for each ticker
        if symbol not in tickers_map:
            tickers_map[symbol] = {
                'symbol': symbol,
                'sentiment_score': float(data.get('sentiment_score', 0.0)),
                'confidence': float(data.get('confidence', 0.0)),
                'timestamp': data.get('timestamp', datetime.now(timezone.utc).isoformat()),
            }
    
    tickers = list(tickers_map.values())
    
    logger.info(f"Fetched sentiment data for {len(tickers)} tickers")
    
    if not tickers:
        logger.warning("No sentiment data found. Consider running sentiment analysis first.")
    
    return {'tickers': tickers}


async def fetch_account_snapshot(db: firestore.Client, tenant_id: str = None) -> Dict[str, Any]:
    """
    Fetch account snapshot from Firestore.
    
    Args:
        db: Firestore client
        tenant_id: Optional tenant ID for multi-tenant setup
    
    Returns:
        Account snapshot dictionary
    """
    logger.info("Fetching account snapshot from Firestore...")
    
    # Build path based on tenant
    if tenant_id:
        doc_path = f"users/{tenant_id}/data/snapshot"
    else:
        # Try to get default user or demo account
        doc_path = "accountSnapshot/latest"
    
    try:
        doc = db.document(doc_path).get()
        
        if doc.exists:
            snapshot = doc.to_dict()
            logger.info(f"Account snapshot loaded: equity=${snapshot.get('equity', '0')}")
            return snapshot
        else:
            logger.warning(f"No account snapshot found at {doc_path}, using mock data")
            return {
                'equity': '100000.00',
                'buying_power': '50000.00',
                'cash': '50000.00',
                'positions': []
            }
    except Exception as e:
        logger.error(f"Error fetching account snapshot: {e}")
        return {
            'equity': '100000.00',
            'buying_power': '50000.00',
            'cash': '50000.00',
            'positions': []
        }


async def execute_signal(
    signal: Dict[str, Any],
    account_snapshot: Dict[str, Any],
    execute: bool = False
) -> bool:
    """
    Execute trading signal via Alpaca API.
    
    Args:
        signal: Trading signal from strategy
        account_snapshot: Current account state
        execute: Whether to actually execute trades
    
    Returns:
        True if execution succeeded
    """
    action = signal['action']
    ticker = signal['ticker']
    allocation = signal['allocation']
    
    if action == 'HOLD':
        logger.info("Signal is HOLD - no trade execution needed")
        return True
    
    # Calculate position size based on allocation and buying power
    buying_power = float(account_snapshot.get('buying_power', 0))
    position_value = buying_power * abs(allocation)
    
    logger.info(f"\n{'=' * 80}")
    logger.info(f"Trade Signal:")
    logger.info(f"  Action:     {action}")
    logger.info(f"  Ticker:     {ticker}")
    logger.info(f"  Allocation: {allocation:.1%}")
    logger.info(f"  Value:      ${position_value:,.2f}")
    logger.info(f"{'=' * 80}\n")
    
    if not execute:
        logger.info("DRY RUN MODE - No actual trade executed")
        return True
    
    # TODO: Implement actual Alpaca trade execution
    logger.warning("Trade execution not yet implemented. Would execute:")
    logger.warning(f"  {action} {ticker} worth ${position_value:,.2f}")
    
    return False


async def write_signal_to_firestore(
    db: firestore.Client,
    signal: Dict[str, Any],
    strategy_name: str,
    tenant_id: str = None
) -> str:
    """
    Write trading signal to Firestore tradingSignals collection.
    
    Args:
        db: Firestore client
        signal: Trading signal dictionary
        strategy_name: Name of the strategy
        tenant_id: Optional tenant ID
    
    Returns:
        Document ID of the written signal
    """
    timestamp = datetime.now(timezone.utc)
    
    signal_doc = {
        'strategy': strategy_name,
        'strategy_name': 'Dynamic Sector Rotation',
        'timestamp': timestamp,
        'action': signal['action'],
        'ticker': signal['ticker'],
        'allocation': signal['allocation'],
        'reasoning': signal['reasoning'],
        'metadata': signal.get('metadata', {}),
        'did_trade': False,  # Update after trade execution
    }
    
    if tenant_id:
        signal_doc['tenant_id'] = tenant_id
    
    # Write to Firestore
    doc_ref = db.collection('tradingSignals').document()
    doc_ref.set(signal_doc)
    
    logger.info(f"Signal written to Firestore: {doc_ref.id}")
    return doc_ref.id


async def run_strategy(
    top_n_sectors: int = 3,
    long_allocation: float = 0.60,
    turnover_threshold: float = 0.20,
    spy_threshold: float = -0.5,
    enable_hedging: bool = True,
    execute: bool = False,
    tenant_id: str = None,
    write_to_firestore: bool = True,
) -> None:
    """
    Main function to run the sector rotation strategy.
    
    Args:
        top_n_sectors: Number of top sectors to allocate to
        long_allocation: Percentage of capital to allocate
        turnover_threshold: Minimum sentiment change to rebalance
        spy_threshold: SPY sentiment threshold for market hedge
        enable_hedging: Enable/disable market hedging
        execute: Whether to actually execute trades
        tenant_id: Optional tenant ID for multi-tenant setup
        write_to_firestore: Whether to write signals to Firestore
    """
    logger.info("=" * 80)
    logger.info("Dynamic Sector Rotation Strategy - Execution")
    logger.info("=" * 80)
    logger.info(f"Configuration:")
    logger.info(f"  Top N Sectors:       {top_n_sectors}")
    logger.info(f"  Long Allocation:     {long_allocation:.1%}")
    logger.info(f"  Turnover Threshold:  {turnover_threshold:.1%}")
    logger.info(f"  SPY Threshold:       {spy_threshold}")
    logger.info(f"  Enable Hedging:      {enable_hedging}")
    logger.info(f"  Execute Trades:      {execute}")
    logger.info(f"  Tenant ID:           {tenant_id or 'default'}")
    logger.info("=" * 80)
    logger.info("")
    
    # Initialize Firebase
    db = init_firebase()
    
    # Create strategy instance
    config = {
        'top_n_sectors': top_n_sectors,
        'long_allocation': long_allocation,
        'turnover_threshold': turnover_threshold,
        'spy_threshold': spy_threshold,
        'enable_hedging': enable_hedging,
    }
    
    strategy = SectorRotationStrategy(name='sector_rotation', config=config)
    logger.info("Strategy initialized successfully")
    logger.info("")
    
    # Fetch market data (sentiment scores)
    market_data = await fetch_sentiment_data(db, tenant_id)
    
    if not market_data.get('tickers'):
        logger.error("No sentiment data available. Cannot proceed.")
        logger.error("Please run sentiment analysis first to generate sentiment scores.")
        return
    
    # Fetch account snapshot
    account_snapshot = await fetch_account_snapshot(db, tenant_id)
    
    # Evaluate strategy
    logger.info("Evaluating strategy...")
    signal = await strategy.evaluate(
        market_data=market_data,
        account_snapshot=account_snapshot,
        regime_data=None  # TODO: Add GEX regime data if available
    )
    
    logger.info("Strategy evaluation completed")
    logger.info("")
    
    # Display signal
    logger.info("=" * 80)
    logger.info("STRATEGY SIGNAL")
    logger.info("=" * 80)
    logger.info(f"Action:      {signal['action']}")
    logger.info(f"Ticker:      {signal['ticker']}")
    logger.info(f"Allocation:  {signal['allocation']:.1%}")
    logger.info("")
    logger.info("Reasoning:")
    logger.info("-" * 80)
    for line in signal['reasoning'].split('\n'):
        logger.info(line)
    logger.info("-" * 80)
    logger.info("")
    
    # Display sector scores
    if 'metadata' in signal and 'sector_scores' in signal['metadata']:
        logger.info("Sector Scores:")
        logger.info("-" * 80)
        sector_scores = signal['metadata']['sector_scores']
        sorted_sectors = sorted(sector_scores.items(), key=lambda x: x[1], reverse=True)
        for sector, score in sorted_sectors:
            status = "🟢" if score > 0.35 else ("⚪" if score > -0.4 else "🔴")
            logger.info(f"  {status} {sector:20s} {score:+.3f}")
        logger.info("-" * 80)
        logger.info("")
    
    # Write signal to Firestore
    if write_to_firestore:
        doc_id = await write_signal_to_firestore(db, signal, 'sector_rotation', tenant_id)
        logger.info(f"Signal saved to Firestore: tradingSignals/{doc_id}")
        logger.info("")
    
    # Execute trade (if enabled)
    if signal['action'] != 'HOLD':
        success = await execute_signal(signal, account_snapshot, execute)
        if success and execute:
            logger.info("✓ Trade executed successfully")
        elif not execute:
            logger.info("ℹ Dry run mode - no trade executed")
        else:
            logger.error("✗ Trade execution failed")
    
    logger.info("")
    logger.info("=" * 80)
    logger.info("Strategy execution completed")
    logger.info("=" * 80)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Run the Dynamic Sector Rotation Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (no trades)
  python scripts/run_sector_rotation_strategy.py
  
  # Execute trades
  python scripts/run_sector_rotation_strategy.py --execute
  
  # Custom configuration
  python scripts/run_sector_rotation_strategy.py --top-n 5 --allocation 0.70
  
  # Disable market hedging
  python scripts/run_sector_rotation_strategy.py --no-hedging
        """
    )
    
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually place trades (default: dry run only)'
    )
    
    parser.add_argument(
        '--top-n',
        type=int,
        default=3,
        help='Number of top sectors to allocate to (default: 3)'
    )
    
    parser.add_argument(
        '--allocation',
        type=float,
        default=0.60,
        help='Percentage of capital to allocate (default: 0.60 = 60%%)'
    )
    
    parser.add_argument(
        '--turnover-threshold',
        type=float,
        default=0.20,
        help='Minimum sentiment change to rebalance (default: 0.20 = 20%%)'
    )
    
    parser.add_argument(
        '--spy-threshold',
        type=float,
        default=-0.5,
        help='SPY sentiment threshold for market hedge (default: -0.5)'
    )
    
    parser.add_argument(
        '--no-hedging',
        action='store_true',
        help='Disable market hedging (SPY override)'
    )
    
    parser.add_argument(
        '--tenant-id',
        type=str,
        help='Tenant ID for multi-tenant setup'
    )
    
    parser.add_argument(
        '--no-firestore',
        action='store_true',
        help='Do not write signals to Firestore'
    )
    
    args = parser.parse_args()
    
    # Run the strategy
    try:
        asyncio.run(run_strategy(
            top_n_sectors=args.top_n,
            long_allocation=args.allocation,
            turnover_threshold=args.turnover_threshold,
            spy_threshold=args.spy_threshold,
            enable_hedging=not args.no_hedging,
            execute=args.execute,
            tenant_id=args.tenant_id,
            write_to_firestore=not args.no_firestore,
        ))
    except KeyboardInterrupt:
        logger.info("\nStrategy execution interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Strategy execution failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
