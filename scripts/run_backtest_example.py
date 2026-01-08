#!/usr/bin/env python3
"""
Quick Start Script for Running Backtests

This script demonstrates how to run a backtest with the Gamma Scalper strategy.

Usage:
    python scripts/run_backtest_example.py

Requirements:
    - APCA_API_KEY_ID environment variable
    - APCA_API_SECRET_KEY environment variable
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta

# Add functions directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../functions"))

from backtester import Backtester
from strategies.gamma_scalper import GammaScalper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


def main():
    """Run a backtest example."""
    
    # Check for API credentials
    if not os.getenv("APCA_API_KEY_ID") or not os.getenv("APCA_API_SECRET_KEY"):
        logger.error(
            "Please set APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables.\n"
            "Example:\n"
            "  export APCA_API_KEY_ID='your_key'\n"
            "  export APCA_API_SECRET_KEY='your_secret'"
        )
        sys.exit(1)
    
    print("\n" + "="*70)
    print("STRATEGY BACKTESTING - QUICK START EXAMPLE")
    print("="*70)
    
    # Configuration
    symbol = "SPY"
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    initial_capital = 100000.0
    
    print(f"\nConfiguration:")
    print(f"  Strategy: 0DTE Gamma Scalper")
    print(f"  Symbol: {symbol}")
    print(f"  Period: {start_date} to {end_date}")
    print(f"  Initial Capital: ${initial_capital:,.2f}")
    print(f"\nNote: This will fetch 1-minute bars from Alpaca (may take a few minutes)")
    
    # Ask for confirmation
    response = input("\nProceed with backtest? (y/n): ")
    if response.lower() != 'y':
        print("Backtest cancelled.")
        sys.exit(0)
    
    print("\n" + "-"*70)
    print("RUNNING BACKTEST...")
    print("-"*70 + "\n")
    
    try:
        # Initialize strategy
        strategy = GammaScalper(config={
            "threshold": 0.15,
            "gex_positive_multiplier": 0.5,
            "gex_negative_multiplier": 1.5
        })
        
        # Create backtester
        backtester = Backtester(
            strategy=strategy,
            symbol=symbol,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            initial_capital=initial_capital
        )
        
        # Run backtest
        results = backtester.run()
        
        # Display results
        print("\n" + "="*70)
        print("BACKTEST RESULTS")
        print("="*70)
        
        metrics = results['metrics']
        
        print(f"\n📊 PERFORMANCE SUMMARY")
        print(f"  Initial Capital:     ${metrics['initial_capital']:>12,.2f}")
        print(f"  Final Equity:        ${metrics['final_equity']:>12,.2f}")
        print(f"  Total Return:        {metrics['total_return']:>12.2%}")
        print(f"  Benchmark Return:    {metrics['benchmark_return']:>12.2%}")
        print(f"  Alpha:               {metrics['alpha']:>12.2%}")
        
        print(f"\n📈 RISK METRICS")
        print(f"  Sharpe Ratio:        {metrics['sharpe_ratio']:>12.2f}")
        print(f"  Max Drawdown:        {metrics['max_drawdown']:>12.2%}")
        
        print(f"\n💰 TRADE STATISTICS")
        print(f"  Total Trades:        {metrics['total_trades']:>12}")
        print(f"  Winning Trades:      {metrics['winning_trades']:>12}")
        print(f"  Losing Trades:       {metrics['losing_trades']:>12}")
        print(f"  Win Rate:            {metrics['win_rate']:>12.2%}")
        
        print(f"\n💵 WIN/LOSS ANALYSIS")
        print(f"  Average Win:         ${metrics['avg_win']:>12,.2f}")
        print(f"  Average Loss:        ${metrics['avg_loss']:>12,.2f}")
        print(f"  Profit Factor:       {metrics['profit_factor']:>12.2f}")
        
        print("\n" + "="*70)
        
        # Interpretation
        print("\n📝 INTERPRETATION:")
        
        if metrics['sharpe_ratio'] > 2.0:
            print("  ✅ Excellent Sharpe Ratio (> 2.0)")
        elif metrics['sharpe_ratio'] > 1.0:
            print("  ✅ Good Sharpe Ratio (> 1.0)")
        elif metrics['sharpe_ratio'] > 0:
            print("  ⚠️  Moderate Sharpe Ratio")
        else:
            print("  ❌ Negative Sharpe Ratio")
        
        if metrics['alpha'] > 0:
            print(f"  ✅ Strategy outperformed benchmark by {metrics['alpha']:.2%}")
        else:
            print(f"  ❌ Strategy underperformed benchmark by {abs(metrics['alpha']):.2%}")
        
        if metrics['max_drawdown'] < 0.10:
            print(f"  ✅ Low drawdown ({metrics['max_drawdown']:.2%})")
        elif metrics['max_drawdown'] < 0.20:
            print(f"  ⚠️  Moderate drawdown ({metrics['max_drawdown']:.2%})")
        else:
            print(f"  ❌ High drawdown ({metrics['max_drawdown']:.2%})")
        
        if metrics['win_rate'] > 0.6:
            print(f"  ✅ High win rate ({metrics['win_rate']:.2%})")
        elif metrics['win_rate'] > 0.5:
            print(f"  ✅ Above 50% win rate ({metrics['win_rate']:.2%})")
        else:
            print(f"  ⚠️  Below 50% win rate ({metrics['win_rate']:.2%})")
        
        # Save results to file
        output_file = f"backtest_results_{symbol}_{start_date}_{end_date}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"\n💾 Full results saved to: {output_file}")
        print("\n" + "="*70)
        
    except Exception as e:
        logger.exception(f"Error running backtest: {e}")
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
