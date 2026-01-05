# Strategy Loader & Registry

## Overview

The Strategy Loader provides a centralized system for managing multiple institutional trading strategies. It automatically discovers all strategies in the `functions/strategies/` directory, evaluates them in parallel, and aggregates their signals into a master recommendation list.

## Architecture

```
functions/
├── strategies/
│   ├── __init__.py          # Package exports
│   ├── base.py              # BaseStrategy (async, dict-based)
│   ├── base_strategy.py     # BaseStrategy (sync, TradingSignal-based)
│   ├── loader.py            # ★ StrategyLoader class
│   ├── gamma_scalper.py     # Example strategy
│   └── example_strategy.py  # Example strategy
└── main.py                  # ★ Cloud Function integration
```

## Key Components

### 1. StrategyLoader Class (`strategies/loader.py`)

The main orchestrator that:
- **Auto-discovers** all strategies inheriting from BaseStrategy
- **Initializes** strategy instances with configuration
- **Evaluates** all strategies in parallel
- **Aggregates** signals into a master recommendation list
- **Saves** results to Firestore

```python
from strategies import StrategyLoader

# Initialize loader
loader = StrategyLoader(db=firestore_client, config={})

# Get all signals
signals = await loader.get_all_signals(
    market_data=market_data,
    account_snapshot=account_snapshot,
    save_to_firestore=True,
    user_id=user_id
)
```

### 2. Auto-Discovery Mechanism

The loader automatically finds and loads **any** class that inherits from:
- `BaseStrategy` (from `base.py`) - async, dict-based signals
- `BaseStrategy` (from `base_strategy.py`) - sync, TradingSignal-based

**To add a new strategy:**
1. Create a file in `functions/strategies/` (e.g., `my_strategy.py`)
2. Inherit from `BaseStrategy`
3. Implement the `evaluate()` method
4. Done! The loader will discover it automatically.

Example:
```python
# functions/strategies/my_strategy.py
from .base_strategy import BaseStrategy, TradingSignal, SignalType

class MyStrategy(BaseStrategy):
    def evaluate(self, market_data, account_snapshot):
        # Your logic here
        return TradingSignal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            reasoning="My strategy says BUY!"
        )
```

### 3. Signal Aggregation (`get_all_signals`)

The `get_all_signals()` method:

1. **Evaluates** all loaded strategies with the same market data and account snapshot
2. **Normalizes** signals to a common format (handles both dict and TradingSignal)
3. **Ranks** signals by confidence (highest first)
4. **Saves** to Firestore:
   - `users/{userId}/master_recommendations/{timestamp}`
   - `users/{userId}/master_recommendations/latest`

Returns:
```python
[
    {
        "strategy_name": "GammaScalper",
        "action": "BUY",
        "confidence": 0.85,
        "reasoning": "Delta hedge rule triggered...",
        "ticker": "SPY",
        "timestamp": "2025-12-30T..."
    },
    {
        "strategy_name": "ExampleStrategy",
        "action": "HOLD",
        "confidence": 0.0,
        "reasoning": "Example strategy holding...",
        ...
    },
    ...
]
```

### 4. Main Integration (`functions/main.py`)

The StrategyLoader is initialized **once per Cloud Function instance** (cold start) and reused across invocations (warm starts):

```python
# Global instance
_strategy_loader: Optional[StrategyLoader] = None

def get_strategy_loader(db: firestore.Client) -> StrategyLoader:
    """Get or create the global StrategyLoader instance."""
    global _strategy_loader
    if _strategy_loader is None:
        _strategy_loader = StrategyLoader(db=db, config={})
    return _strategy_loader
```

#### New Cloud Function: `generate_trading_signal`

```python
@https_fn.on_call()
def generate_trading_signal(req: https_fn.CallableRequest) -> Dict[str, Any]:
    """
    Generate trading signals by evaluating ALL strategies.
    """
    # 1. Get StrategyLoader
    loader = get_strategy_loader(db)
    
    # 2. Get account snapshot from Firestore
    account_snapshot = {...}
    
    # 3. Get market data from Firestore
    market_data = {...}
    
    # 4. Evaluate all strategies
    signals = await loader.get_all_signals(
        market_data=market_data,
        account_snapshot=account_snapshot,
        save_to_firestore=True,
        user_id=user_id
    )
    
    # 5. Return aggregated results
    return {
        "success": True,
        "signals": signals,  # All signals, sorted by confidence
        "top_signal": signals[0],  # Highest confidence
        "total_strategies": len(signals),
        ...
    }
```

## Usage

### From Frontend

```javascript
import { getFunctions, httpsCallable } from 'firebase/functions';

const functions = getFunctions();
const generateSignal = httpsCallable(functions, 'generate_trading_signal');

// Call the function
const result = await generateSignal({ 
    symbol: 'SPY',
    save_to_firestore: true 
});

console.log('Top signal:', result.data.top_signal);
console.log('All signals:', result.data.signals);
```

### From Backend

```python
from strategies import StrategyLoader

# Initialize
loader = StrategyLoader(db=firestore_client)

# Evaluate all strategies
signals = await loader.get_all_signals(
    market_data={
        "symbol": "SPY",
        "price": 450.0,
        "greeks": {...},
        "gex_status": "negative"
    },
    account_snapshot={
        "equity": "10000.00",
        "buying_power": "5000.00",
        "cash": "5000.00",
        "positions": []
    },
    save_to_firestore=True,
    user_id="user123"
)

# Get best signal
best_signal = signals[0]
print(f"Best: {best_signal['action']} {best_signal['ticker']} (confidence: {best_signal['confidence']})")
```

## Firestore Structure

### Master Recommendations
```
users/{userId}/master_recommendations/
├── latest                           # Most recent recommendation (easy access)
│   ├── timestamp: "2025-12-30T..."
│   ├── total_strategies_evaluated: 2
│   ├── signals: [...]
│   └── top_signal: {...}
└── {timestamp_id}                   # Historical recommendations
    ├── timestamp: "2025-12-30T..."
    ├── signals: [...]
    └── ...
```

### Individual Trading Signals (legacy)
```
tradingSignals/
└── {signalId}
    ├── action: "BUY"
    ├── strategy: "GammaScalper"
    ├── confidence: 0.85
    └── ...
```

## Benefits

### 1. **Automatic Discovery**
- Just drop a new strategy file in `functions/strategies/`
- No manual registration needed
- Loader discovers and loads it automatically

### 2. **Parallel Evaluation**
- All strategies evaluated concurrently
- Efficient use of compute resources
- Fast signal generation

### 3. **Unified Signal Format**
- Handles both dict-based and TradingSignal-based strategies
- Normalizes to common format
- Easy to compare and rank

### 4. **Master Recommendation**
- Single source of truth for trading decisions
- All strategies' opinions in one place
- Ranked by confidence for easy decision-making

### 5. **Firestore Integration**
- Automatic saving of results
- Historical tracking of recommendations
- Easy access via "latest" document

## Example Strategies

### Currently Loaded
- **GammaScalper** (`gamma_scalper.py`) - 0DTE options hedging strategy
- **ExampleStrategy** (`example_strategy.py`) - Template/demo strategy
- **AnotherExampleStrategy** (`example_strategy.py`) - Another demo

### Adding Your Own

1. Create `functions/strategies/my_awesome_strategy.py`:

```python
from .base_strategy import BaseStrategy, TradingSignal, SignalType

class MyAwesomeStrategy(BaseStrategy):
    """
    My awesome trading strategy.
    """
    
    def evaluate(self, market_data, account_snapshot):
        """
        Evaluate market conditions and return a signal.
        """
        # Your logic here
        price = market_data.get('price', 0)
        
        if price > 450:
            return TradingSignal(
                signal_type=SignalType.SELL,
                confidence=0.9,
                reasoning="Price too high, selling",
                metadata={"price": price}
            )
        else:
            return TradingSignal(
                signal_type=SignalType.BUY,
                confidence=0.7,
                reasoning="Price attractive, buying",
                metadata={"price": price}
            )
```

2. That's it! The loader will automatically discover and load it.

3. Call `generate_trading_signal` and your strategy will be evaluated along with all others.

## Configuration

You can provide strategy-specific configuration when initializing the loader:

```python
loader = StrategyLoader(
    db=firestore_client,
    config={
        "GammaScalper": {
            "threshold": 0.20,
            "gex_positive_multiplier": 0.6,
            "gex_negative_multiplier": 1.8
        },
        "MyAwesomeStrategy": {
            "my_param": 123
        }
    }
)
```

Each strategy receives its own config dict during initialization.

## Testing

### Verify Strategy Discovery
```python
from strategies import load_strategies

strategies = load_strategies()
print(f"Discovered: {list(strategies.keys())}")
# Output: ['GammaScalper', 'ExampleStrategy', 'AnotherExampleStrategy', ...]
```

### Test Individual Strategy
```python
from strategies import StrategyLoader

loader = StrategyLoader(db=None)
strategy = loader.get_strategy('GammaScalper')

signal = strategy.evaluate(
    market_data={...},
    account_snapshot={...}
)
print(signal.to_dict())
```

### Test Full Pipeline
```python
loader = StrategyLoader(db=firestore_client)

signals = await loader.get_all_signals(
    market_data={...},
    account_snapshot={...},
    save_to_firestore=False  # Don't save during testing
)

print(f"Generated {len(signals)} signals")
for sig in signals:
    print(f"  - {sig['strategy_name']}: {sig['action']} (conf: {sig['confidence']})")
```

## Troubleshooting

### Strategy Not Discovered?
1. Check file is in `functions/strategies/`
2. Check class inherits from `BaseStrategy`
3. Check file doesn't have syntax errors
4. Check `__init__.py` doesn't have conflicting imports

### Evaluation Errors?
- Check logs: Errors are caught and logged with strategy name
- Failed strategies return HOLD signal with error in metadata
- Other strategies continue to evaluate

### Firestore Save Failed?
- Check Firestore client is initialized
- Check user_id is provided
- Check Firestore rules allow write access
- Errors are logged but don't fail the function

## Future Enhancements

Potential improvements:
- [ ] Weighted ensemble (combine multiple strategies)
- [ ] Strategy performance tracking (win rate, Sharpe ratio)
- [ ] Dynamic strategy enable/disable
- [ ] Strategy-specific market data filtering
- [ ] Backtesting framework integration
- [ ] Strategy versioning
- [ ] A/B testing infrastructure

## Summary

The Strategy Loader & Registry provides a powerful, scalable foundation for managing multiple trading strategies:

✅ **Auto-discovery** - No manual registration  
✅ **Parallel evaluation** - Fast signal generation  
✅ **Unified format** - Easy to compare strategies  
✅ **Master recommendations** - Single source of truth  
✅ **Firestore integration** - Automatic persistence  
✅ **Easy to extend** - Just drop in new strategy files  

Ready to scale from 2 strategies to 200+!
