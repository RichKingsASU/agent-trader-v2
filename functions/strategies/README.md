# Strategy Infrastructure

This directory contains the base strategy framework and dynamic loader for the institutional-grade quant suite.

## Overview

The strategy infrastructure provides:
- **BaseStrategy**: Abstract base class defining the standard interface
- **Dynamic Loader**: Automatically discovers and loads strategy implementations
- **Standardized Signals**: Consistent output format across all strategies

## Architecture

```
strategies/
├── __init__.py          # Package exports
├── base.py              # BaseStrategy ABC
├── loader.py            # Dynamic strategy discovery
├── example_strategy.py  # Example implementations
└── your_strategy.py     # Drop your strategies here!
```

## Quick Start

### 1. Create a New Strategy

Create a new file in `strategies/` (e.g., `my_strategy.py`):

```python
from strategies.base import BaseStrategy

class MyAwesomeStrategy(BaseStrategy):
    """Your strategy description"""
    
    async def evaluate(self, market_data: dict, account_snapshot: dict) -> dict:
        # Your logic here
        threshold = self.config.get('threshold', 0.1)
        
        return {
            'action': 'BUY',  # or 'SELL' or 'HOLD'
            'ticker': 'SPY',
            'allocation': 0.2,  # 20% of buying power
            'reasoning': 'Market conditions favorable',
            'strategy_metadata': {
                'threshold': threshold,
                'confidence': 0.85
            }
        }
```

### 2. Use the Strategy

```python
from strategies import instantiate_strategy

# Instantiate your strategy
strategy = instantiate_strategy(
    strategy_name='MyAwesomeStrategy',
    name='my_strategy_instance',
    config={'threshold': 0.15, 'target': 'SPY'}
)

# Evaluate
signal = await strategy.evaluate(market_data, account_snapshot)

# Use the signal
if signal['action'] == 'BUY':
    execute_buy(signal['ticker'], signal['allocation'])
```

### 3. Discover Available Strategies

```python
from strategies import load_strategies, list_strategies, get_strategy_names

# Print all available strategies
list_strategies()

# Get strategy names as a list
names = get_strategy_names()

# Load all strategy classes
strategies = load_strategies()
```

## Signal Format

All strategies must return a standardized signal dictionary:

```python
{
    'action': str,           # 'BUY' | 'SELL' | 'HOLD'
    'ticker': str,           # Symbol to trade
    'allocation': float,     # 0.0 to 1.0 (fraction of buying power)
    'reasoning': str,        # Human-readable explanation
    'strategy_metadata': dict  # Strategy-specific data
}
```

### Field Descriptions

- **action**: Trading action to take
  - `BUY`: Enter or increase position
  - `SELL`: Exit or decrease position
  - `HOLD`: No action required

- **ticker**: Stock symbol (e.g., 'SPY', 'AAPL')

- **allocation**: Position size as fraction of buying power
  - `0.0` = No allocation
  - `0.2` = 20% of buying power
  - `1.0` = All available buying power

- **reasoning**: Clear explanation of why the signal was generated

- **strategy_metadata**: Strategy-specific data (e.g., GEX levels, sentiment scores, technical indicators)

## Input Parameters

### market_data

Current market conditions and data:

```python
{
    'SPY': {
        'price': 450.00,
        'volume': 1000000,
        'bid': 449.99,
        'ask': 450.01
    },
    'timestamp': '2025-12-30T10:00:00Z',
    'indicators': {
        'vix': 15.5,
        'rsi': 65.0
    }
}
```

### account_snapshot

Current account state:

```python
{
    'buying_power': 100000.00,
    'positions': [
        {'ticker': 'SPY', 'quantity': 10, 'avg_price': 440.00}
    ],
    'total_equity': 150000.00,
    'cash': 100000.00
}
```

## Best Practices

### 1. Configuration via config dict

```python
class MyStrategy(BaseStrategy):
    def __init__(self, name: str, config: dict):
        super().__init__(name, config)
        # Access config values with defaults
        self.threshold = config.get('threshold', 0.1)
        self.target = config.get('target', 'SPY')
```

### 2. Async/Await

All `evaluate()` methods must be async to support I/O operations:

```python
async def evaluate(self, market_data: dict, account_snapshot: dict) -> dict:
    # Can call async APIs, databases, etc.
    data = await fetch_external_data()
    return signal
```

### 3. Descriptive Reasoning

Provide clear, actionable reasoning:

```python
# Good
'reasoning': 'GEX resistance at $450, delta momentum negative, closing position'

# Bad
'reasoning': 'Sell signal'
```

### 4. Rich Metadata

Include relevant metrics in strategy_metadata:

```python
'strategy_metadata': {
    'gex_resistance': 450.00,
    'delta_momentum': -0.15,
    'confidence_score': 0.82,
    'risk_level': 'medium'
}
```

## Testing Your Strategy

Create a test script:

```python
import asyncio
from strategies import instantiate_strategy

async def test_strategy():
    strategy = instantiate_strategy(
        strategy_name='MyStrategy',
        name='test',
        config={'threshold': 0.15}
    )
    
    mock_data = {
        'SPY': {'price': 450.00},
        'timestamp': '2025-12-30T10:00:00Z'
    }
    
    mock_account = {
        'buying_power': 100000.00,
        'positions': []
    }
    
    signal = await strategy.evaluate(mock_data, mock_account)
    print(f"Action: {signal['action']}")
    print(f"Reasoning: {signal['reasoning']}")

asyncio.run(test_strategy())
```

## Dynamic Loading

The loader automatically discovers strategies:

1. Scans all `.py` files in `strategies/`
2. Imports each module
3. Finds classes that inherit from `BaseStrategy`
4. Makes them available via `load_strategies()`

**No registration required!** Just drop your strategy file in the folder.

## Example Strategies Included

- **ExampleStrategy**: Template showing basic structure
- **AnotherExampleStrategy**: Multiple strategies in one file

You can remove these once you've created your own strategies.

## Integration with Execution Engine

```python
# In your execution engine
from strategies import load_strategies

# Load all strategies
strategies = load_strategies()

# Instantiate configured strategies
active_strategies = []
for config in strategy_configs:
    strategy = strategies[config['class_name']](
        name=config['name'],
        config=config['params']
    )
    active_strategies.append(strategy)

# Evaluate all strategies
for strategy in active_strategies:
    signal = await strategy.evaluate(market_data, account_snapshot)
    if signal['action'] != 'HOLD':
        await process_signal(signal)
```

## Advanced Patterns

### Multi-Asset Strategies

```python
async def evaluate(self, market_data: dict, account_snapshot: dict) -> dict:
    # Analyze multiple tickers
    spy_price = market_data['SPY']['price']
    qqq_price = market_data['QQQ']['price']
    
    if spy_price / qqq_price > 1.2:
        return {
            'action': 'BUY',
            'ticker': 'QQQ',  # Buy the laggard
            'allocation': 0.3,
            'reasoning': 'QQQ underperforming SPY',
            'strategy_metadata': {'ratio': spy_price / qqq_price}
        }
```

### Position Sizing Based on Account

```python
async def evaluate(self, market_data: dict, account_snapshot: dict) -> dict:
    buying_power = account_snapshot['buying_power']
    
    # Scale allocation based on account size
    if buying_power > 1000000:
        allocation = 0.1  # Conservative for large accounts
    else:
        allocation = 0.3  # More aggressive for smaller accounts
    
    return {...}
```

### Risk Management Integration

```python
async def evaluate(self, market_data: dict, account_snapshot: dict) -> dict:
    # Check existing positions
    positions = account_snapshot.get('positions', [])
    spy_position = next((p for p in positions if p['ticker'] == 'SPY'), None)
    
    if spy_position and spy_position['quantity'] > 100:
        # Already at max position
        return {'action': 'HOLD', ...}
    
    # Generate normal signal
    return {...}
```

## Troubleshooting

### Strategy not found

```python
# Error: Strategy 'MyStrategy' not found
```

**Fixes:**
1. Check file is in `strategies/` directory
2. Class inherits from `BaseStrategy`
3. Class is not abstract (implements `evaluate()`)
4. No import errors in the file

### Import errors

```python
# ModuleNotFoundError
```

**Fix:** Use relative imports in strategy files:
```python
from .base import BaseStrategy  # Correct
# from strategies.base import BaseStrategy  # May cause issues
```

## Next Steps

1. ✅ Base infrastructure created
2. 🔄 Implement your first production strategy
3. 🔄 Integrate with execution engine
4. 🔄 Add backtesting framework
5. 🔄 Deploy to production

---

**Ready to build institutional-grade quant strategies!** 🚀
