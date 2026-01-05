"""
Example usage of MaestroOrchestrator.

This example demonstrates how to use the MaestroOrchestrator to dynamically
allocate capital across specialized trading agents based on their historical
performance (Sharpe Ratios).

Prerequisites:
- Firebase Admin SDK initialized
- Firestore collection 'users/{uid}/tradeJournal/' with trade data
- Each trade must have 'agent_id' field matching configured agent IDs

Run:
    python3 example_maestro_usage.py
"""

import os
import sys
from decimal import Decimal
from typing import Dict, Any
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_basic_usage():
    """
    Example 1: Basic usage of MaestroOrchestrator.
    
    This example shows how to initialize the Maestro and calculate
    agent weights for a given user.
    """
    print("\n" + "="*70)
    print("EXAMPLE 1: Basic MaestroOrchestrator Usage")
    print("="*70 + "\n")
    
    try:
        from maestro_orchestrator import MaestroOrchestrator
        
        # Initialize with default configuration
        maestro = MaestroOrchestrator()
        
        print("✅ MaestroOrchestrator initialized with default config")
        print(f"   - Tracking {len(maestro.agent_ids)} agents: {maestro.agent_ids}")
        print(f"   - Lookback period: {maestro.lookback_trades} trades")
        print(f"   - Risk-free rate: {maestro.risk_free_rate} (annual)")
        print(f"   - Floor weight: {maestro.min_floor_weight} for negative Sharpe")
        print(f"   - Strict enforcement: {maestro.enforce_performance}")
        
        # Note: Actual weight calculation requires Firebase connection
        print("\n⚠️  To calculate actual weights, you need:")
        print("   1. Firebase Admin SDK initialized")
        print("   2. User ID with trade history in Firestore")
        print("   3. Trades with 'agent_id' field matching configured agents")
        
        print("\nExample call:")
        print("   weights = maestro.calculate_agent_weights('user123')")
        print("   # Returns: {'WhaleFlowAgent': Decimal('0.45'), ...}")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("   Make sure Firebase Admin SDK is installed: pip install firebase-admin")


def example_custom_configuration():
    """
    Example 2: Custom configuration.
    
    Shows how to customize the Maestro with specific parameters.
    """
    print("\n" + "="*70)
    print("EXAMPLE 2: Custom Configuration")
    print("="*70 + "\n")
    
    try:
        from maestro_orchestrator import MaestroOrchestrator
        
        # Custom configuration
        config = {
            # Define which agents to track
            'agent_ids': [
                'WhaleFlowAgent',
                'SentimentAgent',
                'GammaScalper',
                'SectorRotation',
                'MomentumAgent'
            ],
            
            # Analyze last 150 trades per agent (instead of default 100)
            'lookback_trades': 150,
            
            # Use 3% annual risk-free rate (instead of default 4%)
            'risk_free_rate': '0.03',
            
            # Set minimum floor weight to 10% for negative Sharpe agents
            'min_floor_weight': '0.10',
            
            # Enforce strict performance: zero weight for negative Sharpe
            'enforce_performance': True
        }
        
        maestro = MaestroOrchestrator(config=config)
        
        print("✅ MaestroOrchestrator initialized with custom config:")
        print(f"   - Agents: {maestro.agent_ids}")
        print(f"   - Lookback: {maestro.lookback_trades} trades")
        print(f"   - Risk-free rate: {float(maestro.risk_free_rate)*100:.1f}%")
        print(f"   - Floor weight: {float(maestro.min_floor_weight)*100:.0f}%")
        print(f"   - Strict mode: {maestro.enforce_performance}")
        
        print("\n💡 With enforce_performance=True:")
        print("   - Agents with negative Sharpe get 0% allocation")
        print("   - Only profitable agents receive capital")
        print("   - More aggressive performance-based filtering")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")


def example_integration_with_strategy():
    """
    Example 3: Integration with standard strategy evaluation.
    
    Shows how to use Maestro in the standard BaseStrategy lifecycle.
    """
    print("\n" + "="*70)
    print("EXAMPLE 3: Integration with Strategy Evaluation")
    print("="*70 + "\n")
    
    try:
        from maestro_orchestrator import MaestroOrchestrator
        
        maestro = MaestroOrchestrator()
        
        # Mock account snapshot (in production, this comes from Alpaca)
        account_snapshot = {
            'user_id': 'user123',  # Required for Firestore query
            'equity': '100000',
            'buying_power': '50000',
            'cash': '50000',
            'positions': []
        }
        
        # Mock market data
        market_data = {
            'symbol': 'SPY',
            'price': 450.0,
            'vix': 18.5
        }
        
        print("📊 Calling maestro.evaluate()...")
        print(f"   Account equity: ${account_snapshot['equity']}")
        print(f"   User ID: {account_snapshot['user_id']}")
        
        # In production, this would query Firestore and calculate weights
        # signal = maestro.evaluate(market_data, account_snapshot)
        
        print("\n✅ Expected signal structure:")
        print("   signal.signal_type = SignalType.HOLD")
        print("   signal.confidence = 1.0")
        print("   signal.metadata = {")
        print("       'weights': {")
        print("           'WhaleFlowAgent': 0.45,")
        print("           'SentimentAgent': 0.30,")
        print("           'GammaScalper': 0.20,")
        print("           'SectorRotation': 0.05")
        print("       },")
        print("       'agent_ids': [...],")
        print("       'lookback_trades': 100,")
        print("       'risk_free_rate': 0.04")
        print("   }")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")


def example_manual_calculations():
    """
    Example 4: Manual calculation demonstration.
    
    Shows the internal calculations without Firestore dependency.
    """
    print("\n" + "="*70)
    print("EXAMPLE 4: Manual Calculation Demonstration")
    print("="*70 + "\n")
    
    try:
        from maestro_orchestrator import MaestroOrchestrator
        
        maestro = MaestroOrchestrator()
        
        # Simulate trade data for demonstration
        print("📈 Simulating trade data for 3 agents...\n")
        
        # Agent 1: WhaleFlowAgent (good performance)
        trades_agent1 = [
            {
                'trade_id': f'wf_{i}',
                'agent_id': 'WhaleFlowAgent',
                'realized_pnl': '100',
                'entry_price': '100',
                'quantity': '10'
            }
            for i in range(10)
        ]
        
        # Agent 2: SentimentAgent (medium performance)
        trades_agent2 = [
            {
                'trade_id': f'sa_{i}',
                'agent_id': 'SentimentAgent',
                'realized_pnl': '50' if i % 2 == 0 else '-25',
                'entry_price': '100',
                'quantity': '10'
            }
            for i in range(10)
        ]
        
        # Agent 3: GammaScalper (poor performance)
        trades_agent3 = [
            {
                'trade_id': f'gs_{i}',
                'agent_id': 'GammaScalper',
                'realized_pnl': '-50',
                'entry_price': '100',
                'quantity': '10'
            }
            for i in range(10)
        ]
        
        # Calculate returns for each agent
        for agent_name, trades in [
            ('WhaleFlowAgent', trades_agent1),
            ('SentimentAgent', trades_agent2),
            ('GammaScalper', trades_agent3)
        ]:
            print(f"Agent: {agent_name}")
            
            returns = maestro._calculate_daily_returns(trades)
            
            if returns:
                mean_return = sum(returns) / Decimal(str(len(returns)))
                sharpe = maestro._calculate_sharpe_ratio(returns)
                
                print(f"  - Trades: {len(returns)}")
                print(f"  - Mean return: {float(mean_return):.2f}%")
                print(f"  - Sharpe Ratio: {float(sharpe):.4f}")
            else:
                print(f"  - No valid returns calculated")
            
            print()
        
        # Demonstrate Softmax normalization
        print("📊 Softmax normalization example:\n")
        
        sharpe_ratios = {
            'WhaleFlowAgent': Decimal('2.0'),
            'SentimentAgent': Decimal('1.0'),
            'GammaScalper': Decimal('-0.5')
        }
        
        print("Input Sharpe Ratios:")
        for agent, sharpe in sharpe_ratios.items():
            print(f"  {agent}: {float(sharpe):.2f}")
        
        weights = maestro._softmax_normalize(sharpe_ratios)
        
        print("\nOutput Weights (Softmax):")
        for agent, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            print(f"  {agent}: {float(weight)*100:.2f}%")
        
        total = sum(weights.values())
        print(f"\nTotal weight: {float(total):.4f} (should be 1.0000)")
        
    except ImportError as e:
        print(f"❌ Import error: {e}")


def example_firestore_schema():
    """
    Example 5: Required Firestore schema.
    
    Shows the expected data structure in Firestore.
    """
    print("\n" + "="*70)
    print("EXAMPLE 5: Required Firestore Schema")
    print("="*70 + "\n")
    
    print("📚 Collection Path:")
    print("   users/{uid}/tradeJournal/{tradeId}")
    print()
    
    print("📋 Required Fields:")
    print("   - agent_id (string): Agent identifier, e.g., 'WhaleFlowAgent'")
    print("   - closed_at (timestamp): When trade was closed (for ordering)")
    print("   - realized_pnl (string): Profit/loss as Decimal string, e.g., '123.45'")
    print("   - entry_price (string): Entry price as Decimal string")
    print("   - quantity (string): Number of shares as Decimal string")
    print()
    
    print("📄 Example Document:")
    print("""
    {
      "trade_id": "trade_12345",
      "user_id": "user123",
      "agent_id": "WhaleFlowAgent",  // ← REQUIRED
      "symbol": "AAPL",
      "side": "BUY",
      "entry_price": "150.25",       // ← REQUIRED (Decimal as string)
      "exit_price": "155.50",
      "quantity": "100",              // ← REQUIRED (Decimal as string)
      "realized_pnl": "525.00",       // ← REQUIRED (Decimal as string)
      "created_at": Timestamp,
      "closed_at": Timestamp,         // ← REQUIRED (for ordering)
      "analyzed_at": Timestamp,
      "quant_grade": "A-",
      "ai_feedback": "Excellent entry timing..."
    }
    """)
    
    print("🔍 Required Composite Index:")
    print("""
    Collection: tradeJournal
    Fields:
      - agent_id (ASCENDING)
      - closed_at (DESCENDING)
    
    To create this index:
      firebase deploy --only firestore:indexes
    """)


def main():
    """Run all examples."""
    print("\n" + "="*70)
    print("MAESTRO ORCHESTRATOR - USAGE EXAMPLES")
    print("="*70)
    
    examples = [
        example_basic_usage,
        example_custom_configuration,
        example_integration_with_strategy,
        example_manual_calculations,
        example_firestore_schema
    ]
    
    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"\n❌ Error in {example.__name__}: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "="*70)
    print("✅ Examples complete!")
    print("="*70)
    print("\nNext steps:")
    print("1. Install dependencies: pip install firebase-admin")
    print("2. Initialize Firebase Admin SDK in your application")
    print("3. Create Firestore composite index (see Example 5)")
    print("4. Ensure trade data has 'agent_id' field")
    print("5. Call maestro.calculate_agent_weights(user_id)")
    print("\nFor more information, see: MAESTRO_ORCHESTRATOR_README.md")
    print()


if __name__ == '__main__':
    main()
