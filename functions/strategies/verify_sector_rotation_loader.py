#!/usr/bin/env python3
"""
Verification script to confirm that SectorRotationStrategy is properly
discovered and loaded by the StrategyLoader.

This script:
1. Initializes the StrategyLoader
2. Checks if SectorRotationStrategy is in the registry
3. Instantiates the strategy
4. Runs a basic evaluation test
5. Prints results

Usage:
    python verify_sector_rotation_loader.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from strategies.loader import get_strategy_loader


def main():
    """Main verification function."""
    print("=" * 80)
    print("Sector Rotation Strategy - Loader Verification")
    print("=" * 80)
    print()
    
    # Step 1: Initialize the loader
    print("[1/5] Initializing StrategyLoader...")
    try:
        loader = get_strategy_loader()
        print(f"✓ StrategyLoader initialized successfully")
    except Exception as e:
        print(f"✗ Failed to initialize StrategyLoader: {e}")
        return False
    
    print()
    
    # Step 2: Check loaded strategies
    print("[2/5] Checking loaded strategies...")
    strategy_names = loader.get_strategy_names()
    print(f"✓ Found {len(strategy_names)} strategies:")
    for name in strategy_names:
        print(f"  - {name}")
    
    print()
    
    # Step 3: Verify SectorRotationStrategy is loaded
    print("[3/5] Verifying SectorRotationStrategy is loaded...")
    if 'SectorRotationStrategy' in strategy_names:
        print("✓ SectorRotationStrategy is loaded")
    else:
        print("✗ SectorRotationStrategy NOT FOUND in loader registry")
        print("\nAvailable strategies:")
        for name in strategy_names:
            print(f"  - {name}")
        
        # Check for load errors
        errors = loader.get_load_errors()
        if errors:
            print("\nLoad errors:")
            for name, error in errors.items():
                print(f"  - {name}: {error}")
        
        return False
    
    print()
    
    # Step 4: Get the strategy instance
    print("[4/5] Getting SectorRotationStrategy instance...")
    try:
        strategy = loader.get_strategy('SectorRotationStrategy')
        if strategy is None:
            print("✗ Strategy instance is None")
            return False
        print(f"✓ Strategy instance retrieved: {strategy.__class__.__name__}")
        print(f"  - Config: {strategy.config}")
        print(f"  - Top N sectors: {strategy.top_n_sectors}")
        print(f"  - Long allocation: {strategy.long_allocation}")
    except Exception as e:
        print(f"✗ Failed to get strategy instance: {e}")
        return False
    
    print()
    
    # Step 5: Test evaluation with mock data
    print("[5/5] Testing strategy evaluation with mock data...")
    
    # Create mock market data with sentiment scores
    mock_market_data = {
        'tickers': [
            # Technology - Bullish
            {'symbol': 'AAPL', 'sentiment_score': 0.75, 'confidence': 0.85},
            {'symbol': 'MSFT', 'sentiment_score': 0.70, 'confidence': 0.80},
            {'symbol': 'NVDA', 'sentiment_score': 0.80, 'confidence': 0.90},
            
            # Finance - Neutral
            {'symbol': 'JPM', 'sentiment_score': 0.40, 'confidence': 0.70},
            {'symbol': 'BAC', 'sentiment_score': 0.35, 'confidence': 0.65},
            
            # Healthcare - Bullish
            {'symbol': 'UNH', 'sentiment_score': 0.50, 'confidence': 0.75},
            {'symbol': 'JNJ', 'sentiment_score': 0.45, 'confidence': 0.70},
            
            # SPY - Neutral (no systemic risk)
            {'symbol': 'SPY', 'sentiment_score': 0.30, 'confidence': 0.80},
        ]
    }
    
    mock_account_snapshot = {
        'equity': '100000.00',
        'buying_power': '50000.00',
        'cash': '50000.00',
        'positions': []
    }
    
    try:
        # Run evaluation
        signal = asyncio.run(strategy.evaluate(
            market_data=mock_market_data,
            account_snapshot=mock_account_snapshot,
            regime_data=None
        ))
        
        print("✓ Strategy evaluation completed successfully")
        print()
        print("Signal Output:")
        print("-" * 80)
        print(f"Action:      {signal['action']}")
        print(f"Ticker:      {signal['ticker']}")
        print(f"Allocation:  {signal['allocation']:.1%}")
        print(f"Reasoning:")
        print()
        for line in signal['reasoning'].split('\n'):
            print(f"  {line}")
        print("-" * 80)
        
        # Validate signal structure
        required_fields = ['action', 'allocation', 'ticker', 'reasoning', 'metadata']
        missing_fields = [f for f in required_fields if f not in signal]
        
        if missing_fields:
            print(f"\n⚠ Warning: Signal missing required fields: {missing_fields}")
        else:
            print("\n✓ Signal has all required fields")
        
        # Check metadata
        if 'metadata' in signal:
            metadata = signal['metadata']
            print(f"\nMetadata:")
            print(f"  - Strategy: {metadata.get('strategy', 'N/A')}")
            print(f"  - Signal Type: {metadata.get('signal_type', 'N/A')}")
            if 'sector_scores' in metadata:
                print(f"  - Sector Scores:")
                for sector, score in metadata['sector_scores'].items():
                    print(f"      {sector}: {score:.3f}")
        
    except Exception as e:
        print(f"✗ Strategy evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 80)
    print("✓ All verification checks passed!")
    print("=" * 80)
    return True


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
