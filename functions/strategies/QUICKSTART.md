# Strategy Loader Quick Start

## 🚀 Add a New Strategy (3 Steps)

### 1. Create Strategy File

Create `functions/strategies/my_strategy.py`:

```python
from .base_strategy import BaseStrategy, TradingSignal, SignalType

class MyStrategy(BaseStrategy):
    """My trading strategy description."""
    
    def evaluate(self, market_data, account_snapshot):
        # Your logic here
        return TradingSignal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            reasoning="My reason"
        )
```

### 2. That's It!

No registration needed. The loader automatically discovers it.

### 3. Test It

```python
from strategies import StrategyLoader

loader = StrategyLoader(db=firestore_client)
print(loader.get_strategy_names())
# Output: ['GammaScalper', 'ExampleStrategy', 'MyStrategy', ...]
```

---

## 📞 Call from Frontend

```javascript
import { getFunctions, httpsCallable } from 'firebase/functions';

const functions = getFunctions();
const generateSignal = httpsCallable(functions, 'generate_trading_signal');

const result = await generateSignal({ symbol: 'SPY' });

console.log('Best Signal:', result.data.top_signal);
// Output:
// {
//   strategy_name: "MyStrategy",
//   action: "BUY",
//   confidence: 0.8,
//   reasoning: "My reason",
//   ticker: "SPY"
// }

console.log('All Signals:', result.data.signals);
// Array of all strategy signals, sorted by confidence
```

---

## 🐍 Call from Python

```python
from strategies import StrategyLoader

# Initialize
loader = StrategyLoader(db=firestore_client)

# Get all signals
signals = await loader.get_all_signals(
    market_data={
        "symbol": "SPY",
        "price": 450.0,
        "greeks": {"delta": 0.5, "gamma": 0.02},
        "gex_status": "negative"
    },
    account_snapshot={
        "equity": "10000.00",
        "buying_power": "5000.00",
        "positions": []
    }
)

# Best signal
print(signals[0])
```

---

## 🔧 Configure Strategies

```python
loader = StrategyLoader(
    db=firestore_client,
    config={
        "GammaScalper": {
            "threshold": 0.20,
            "gex_positive_multiplier": 0.6
        },
        "MyStrategy": {
            "param1": 100,
            "param2": "value"
        }
    }
)
```

---

## 📊 Access Stored Signals

### Latest Recommendation
```javascript
const latest = await getDoc(
  doc(db, 'users', userId, 'master_recommendations', 'latest')
);
console.log(latest.data());
```

### Historical Recommendations
```javascript
const history = await getDocs(
  collection(db, 'users', userId, 'master_recommendations')
);
```

---

## 🎯 Signal Format

Every signal contains:

```typescript
{
  strategy_name: string;      // e.g., "GammaScalper"
  action: string;             // "BUY" | "SELL" | "HOLD" | "CLOSE_ALL"
  confidence: number;         // 0.0 to 1.0
  reasoning: string;          // Human-readable explanation
  ticker?: string;            // Optional symbol
  timestamp: string;          // ISO timestamp
  metadata?: object;          // Strategy-specific data
}
```

---

## 🧪 Test Your Strategy

```python
# Test just your strategy
from strategies.my_strategy import MyStrategy

strategy = MyStrategy(config={})
signal = strategy.evaluate(
    market_data={"price": 450.0, ...},
    account_snapshot={"equity": "10000", ...}
)
print(signal.to_dict())
```

---

## 📝 Strategy Template

Copy this template for new strategies:

```python
from .base_strategy import BaseStrategy, TradingSignal, SignalType
from typing import Dict, Any

class MyStrategy(BaseStrategy):
    """
    Brief description of what this strategy does.
    
    Config parameters:
        - param1: Description
        - param2: Description
    """
    
    def __init__(self, config=None):
        super().__init__(config)
        # Initialize your parameters
        self.param1 = self.config.get('param1', default_value)
    
    def evaluate(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any]
    ) -> TradingSignal:
        """
        Evaluate and return a signal.
        
        Args:
            market_data: {symbol, price, greeks, gex_status}
            account_snapshot: {equity, buying_power, cash, positions}
        
        Returns:
            TradingSignal
        """
        # Your logic here
        
        return TradingSignal(
            signal_type=SignalType.HOLD,
            confidence=0.5,
            reasoning="Explain your decision",
            metadata={"custom_data": "here"}
        )
```

---

## 🔍 Debugging

### Check Discovered Strategies
```python
from strategies import load_strategies
print(load_strategies().keys())
```

### Check Loader Status
```python
loader = StrategyLoader(db=None)
print(f"Loaded: {loader.get_strategy_names()}")
print(f"Total: {len(loader.strategies)}")
```

### View Logs
```bash
# Cloud Functions logs
gcloud functions logs read generate_trading_signal --limit 50
```

---

## 🎓 Learn More

See [STRATEGY_LOADER_README.md](./STRATEGY_LOADER_README.md) for:
- Architecture details
- Advanced configuration
- Firestore structure
- Troubleshooting

---

## ✅ Checklist for New Strategy

- [ ] Create `functions/strategies/my_strategy.py`
- [ ] Inherit from `BaseStrategy`
- [ ] Implement `evaluate()` method
- [ ] Return `TradingSignal` object
- [ ] Test locally
- [ ] Deploy to Cloud Functions
- [ ] Verify in logs/Firestore
- [ ] Monitor performance

Done! 🎉
