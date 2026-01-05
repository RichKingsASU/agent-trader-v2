# Quick Start: Dynamic Strategy Loader

## 🚀 30-Second Overview

The Dynamic Strategy Loader automatically discovers and runs all trading strategies in parallel. Just drop a new `.py` file in `functions/strategies/` and it's automatically loaded!

## ✅ What's Implemented

- ✅ Automatic strategy discovery (no manual imports)
- ✅ Parallel execution with `asyncio.gather`
- ✅ Master signal aggregation (weighted average)
- ✅ Error isolation (one failure doesn't stop others)
- ✅ Fintech precision (Decimal/String for prices)
- ✅ Global variable reuse (Cloud Functions optimization)

## 📝 Adding a New Strategy

### Step 1: Create Strategy File

Create `functions/strategies/momentum_strategy.py`:

```python
from .base_strategy import BaseStrategy, TradingSignal, SignalType
from decimal import Decimal

class MomentumStrategy(BaseStrategy):
    """Momentum-based trading strategy."""
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        # Your strategy logic
        price = Decimal(str(market_data.get('price', 0)))
        
        # Example: Buy if price > 450
        if price > Decimal('450'):
            return TradingSignal(
                signal_type=SignalType.BUY,
                confidence=0.8,
                reasoning=f"Price ${price} above momentum threshold",
                metadata={"threshold": "450"}
            )
        else:
            return TradingSignal(
                signal_type=SignalType.HOLD,
                confidence=0.5,
                reasoning=f"Price ${price} below momentum threshold"
            )
```

### Step 2: Deploy

```bash
# That's it! No imports needed, no registration required
firebase deploy --only functions
```

The loader automatically:
1. Discovers your new strategy
2. Instantiates it
3. Includes it in parallel evaluation
4. Aggregates its signal with others

## 🧪 Testing Locally

```bash
cd /workspace
python3 test_strategy_loader.py
```

Expected output:
```
✓ Loaded 3 strategies  # Now includes your MomentumStrategy!
✓ Parallel evaluation working
✓ Signal aggregation working
🎉 ALL TESTS PASSED!
```

## 📊 Calling from Frontend

```typescript
import { getFunctions, httpsCallable } from 'firebase/functions';

const functions = getFunctions();
const generateSignal = httpsCallable(functions, 'generate_trading_signal');

// Call the function
const result = await generateSignal({
    symbol: 'SPY',
    aggregation_mode: 'weighted_average'  // or 'log_all'
});

// Response structure
console.log(result.data);
/*
{
    "success": true,
    "master_signal": {
        "action": "BUY",
        "confidence": 0.85,
        "reasoning": "Aggregated from 3 strategies...",
        "allocation": 0.85,
        "ticker": "SPY"
    },
    "all_signals": {
        "GammaScalper": { "action": "BUY", "confidence": 0.9 },
        "MomentumStrategy": { "action": "BUY", "confidence": 0.8 },
        "ExampleStrategy": { "action": "HOLD", "confidence": 0.1 }
    },
    "strategies_evaluated": 3,
    "execution": { "success": true, "trade_id": "..." },
    "timestamp": "2025-12-30T19:43:06Z"
}
*/
```

## 🔍 Aggregation Modes

### Weighted Average (Default)
Strategies "vote" on actions, weighted by their confidence:
```
GammaScalper:      BUY (0.9) → BUY vote gets +0.9
MomentumStrategy:  BUY (0.8) → BUY vote gets +0.8
ExampleStrategy:   HOLD (0.1) → HOLD vote gets +0.1

Result: BUY wins with 1.7 votes
Master confidence: 1.7 / 2.0 = 0.85
```

### Log All
Returns highest-confidence signal, but includes all signals in metadata:
```typescript
const result = await generateSignal({
    symbol: 'SPY',
    aggregation_mode: 'log_all'  // All signals logged for debugging
});

// Best signal is returned as master_signal
// All signals are in master_signal.metadata.all_signals
```

## 🛡️ Error Handling

If a strategy fails, the system continues:

```
2025-12-30 19:43:06 - ERROR - Strategy MyBrokenStrategy: division by zero
2025-12-30 19:43:06 - INFO - ✅ Evaluated 3 strategies. Errors: 1
2025-12-30 19:43:06 - INFO - Master signal: BUY (from 2 working strategies)
```

Failed strategies automatically return:
```python
{
    "action": "HOLD",
    "confidence": 0.0,
    "reasoning": "Error in MyBrokenStrategy: division by zero",
    "error": "division by zero"
}
```

## 📈 Signal Structure

All strategies must return this format:

```python
TradingSignal(
    signal_type=SignalType.BUY,      # BUY, SELL, HOLD, or CLOSE_ALL
    confidence=0.85,                  # 0.0 to 1.0
    reasoning="Why this signal",      # Human-readable explanation
    metadata={"custom": "data"}       # Optional: strategy-specific data
)
```

Or as a dict (for async strategies):
```python
{
    "action": "BUY",                  # BUY, SELL, HOLD, or CLOSE_ALL
    "ticker": "SPY",                  # Trading symbol
    "allocation": 0.85,               # 0.0 to 1.0 of buying power
    "reasoning": "Why this signal",   # Human-readable explanation
    "strategy_metadata": {}           # Optional: strategy-specific data
}
```

## 🔥 Advanced: Strategy Configuration

Pass config to specific strategies:

```typescript
const result = await generateSignal({
    symbol: 'SPY',
    config: {
        threshold: 0.20,              // Override default threshold
        gex_positive_multiplier: 0.3  // Override GEX multiplier
    }
});
```

Config is passed to all strategies in their constructor:
```python
class MyStrategy(BaseStrategy):
    def __init__(self, config=None):
        super().__init__(config)
        self.threshold = Decimal(str(config.get('threshold', 0.15)))
```

## 📍 Where Data is Saved

Every signal is saved to Firestore:
```
users/{userId}/signals/{signalId}
{
    "user_id": "user123",
    "symbol": "SPY",
    "master_signal": { ... },
    "all_signals": { ... },
    "aggregation_mode": "weighted_average",
    "market_regime": "SHORT_GAMMA",
    "execution": { ... },
    "timestamp": ServerTimestamp
}
```

## 🐛 Debugging

View logs in Google Cloud Console:
```bash
gcloud functions logs read generate_trading_signal --limit 50
```

Look for these indicators:
- 🚀 Starting evaluation
- 🔄 Evaluating strategies
- ✅ Evaluation complete
- 📊 Master signal
- 💾 Saved to Firestore
- ❌ Errors (if any)

## 🎯 Next Steps

1. **Create your first strategy** (see Step 1 above)
2. **Test locally** with `test_strategy_loader.py`
3. **Deploy** with `firebase deploy --only functions`
4. **Call from frontend** (see example above)
5. **Monitor signals** in Firestore console

## 💡 Pro Tips

1. **Use Decimal for prices**: `price = Decimal(str(market_data['price']))`
2. **Handle missing data**: Check if fields exist before accessing
3. **Add metadata**: Include useful debug info in signal metadata
4. **Test error cases**: Make sure your strategy handles bad data
5. **Log important decisions**: Use `logger.info()` for key logic paths

## 🆘 Common Issues

**Q: My strategy isn't being loaded**
- Check file is in `functions/strategies/`
- Ensure class inherits from `BaseStrategy`
- Look for import errors in logs

**Q: Strategy loads but evaluation fails**
- Check `evaluate()` method signature matches BaseStrategy
- Ensure you're returning correct signal format
- Look for exceptions in Cloud Logging

**Q: Aggregation gives unexpected results**
- Verify your confidence values are 0.0 to 1.0
- Check signal action is "BUY", "SELL", or "HOLD" (uppercase)
- Use `aggregation_mode: "log_all"` to debug

**Q: How do I disable a strategy?**
- Rename file to `_disabled_momentum_strategy.py` (loader skips files starting with `_`)
- Or move to `functions/strategies/archive/` subfolder

## 📚 Full Documentation

See `DYNAMIC_STRATEGY_LOADER_IMPLEMENTATION.md` for complete details.
