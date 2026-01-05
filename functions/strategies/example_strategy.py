"""
Example Strategy - Demonstrates BaseStrategy Implementation

This is a simple example strategy that shows how to implement the BaseStrategy
interface. It can be used as a template for creating new strategies.
"""

from .base import BaseStrategy


class ExampleStrategy(BaseStrategy):
    """
    A simple example strategy that demonstrates the BaseStrategy interface.
    
    This strategy evaluates market conditions and returns signals based on
    configured thresholds. It's meant as a starting template.
    """
    
    async def evaluate(
        self,
        market_data: dict,
        account_snapshot: dict,
        regime: str = None
    ) -> dict:
        """
        Evaluate market conditions and return a trading signal.
        
        Args:
            market_data: Current market data (prices, indicators, etc.)
            account_snapshot: Current account state (buying power, positions, etc.)
            regime: Optional market regime from GEX engine
            
        Returns:
            A standardized signal dictionary with cryptographic signature
        """
        # Example logic: always return HOLD
        # In a real strategy, you would analyze market_data and account_snapshot
        
        threshold = self.config.get('threshold', 0.1)
        target_ticker = self.config.get('target', 'SPY')
        
        signal = {
            'action': 'HOLD',
            'ticker': target_ticker,
            'allocation': 0.0,
            'reasoning': f'Example strategy with threshold {threshold} - currently holding',
            'metadata': {
                'threshold': threshold,
                'market_data_keys': list(market_data.keys()),
                'account_keys': list(account_snapshot.keys())
            }
        }
        
        # CRITICAL: Sign the signal with agent's cryptographic identity
        # This provides non-repudiation and prevents signal tampering
        signed_signal = self.sign_signal(signal)
        
        return signed_signal


class AnotherExampleStrategy(BaseStrategy):
    """
    Another example strategy to demonstrate multiple strategies in one file.
    
    The loader will discover both strategies in this file.
    """
    
    async def evaluate(
        self,
        market_data: dict,
        account_snapshot: dict,
        regime: str = None
    ) -> dict:
        """Minimal example that returns a BUY signal with cryptographic signature."""
        signal = {
            'action': 'BUY',
            'ticker': self.config.get('target', 'QQQ'),
            'allocation': 0.1,
            'reasoning': 'Another example strategy - demonstrating BUY signal',
            'metadata': {
                'strategy_type': 'example',
                'version': '1.0'
            }
        }
        
        # Sign signal for Zero-Trust verification
        return self.sign_signal(signal)
