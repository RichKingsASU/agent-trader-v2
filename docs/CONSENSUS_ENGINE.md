# Multi-Agent Consensus Trading Signal Layer

## Overview

The Consensus Engine implements an **ensemble-based** approach to trading signal generation where multiple strategies "vote" on a trade, and execution only occurs when there's strong agreement among strategies.

This design reduces false signals, improves decision quality, and provides transparency into which strategies are aligned or in conflict.

## 🎯 Key Features

- **Dynamic Strategy Loading**: Automatically discovers all strategies from the `strategies/` folder
- **Weighted Voting System**: Assign custom weights to strategies based on historical performance
- **Consensus Threshold**: Only execute trades when agreement exceeds configurable threshold (default 0.7)
- **Discordance Tracking**: Logs disagreements to Firestore to identify underperforming strategies
- **Signal Normalization**: Supports both `BaseStrategy` and legacy dict-based signal formats
- **Firestore Integration**: Comprehensive logging for performance analysis and auditing

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    generate_consensus_signal()              │
│                   (Cloud Function Endpoint)                 │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                      ConsensusEngine                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 1. Load all strategies from strategies/ folder      │   │
│  │ 2. Gather votes from each strategy                  │   │
│  │ 3. Normalize signals to StrategyVote format         │   │
│  │ 4. Calculate weighted consensus score               │   │
│  │ 5. Measure discordance (disagreement)               │   │
│  │ 6. Determine if should execute (score > threshold)  │   │
│  │ 7. Log results to Firestore                         │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
         ┌───────────────────────────────────┐
         │      Individual Strategies         │
         ├───────────────────────────────────┤
         │  • GammaScalper                   │
         │  • SentimentAlpha                 │
         │  • FlowTrend                      │
         │  • CongressionalAlpha             │
         │  • Your Custom Strategy           │
         └───────────────────────────────────┘
```

## 📊 Consensus Algorithm

### Vote Collection

Each strategy evaluates market conditions and returns a signal:

```python
class GammaScalper(BaseStrategy):
    def evaluate(self, market_data, account_snapshot, regime):
        # Strategy logic...
        return TradingSignal(
            signal_type=SignalType.BUY,
            confidence=0.85,
            reasoning="Delta threshold exceeded"
        )
```

### Signal Normalization

All signals are normalized to a standard `StrategyVote` format:

```python
StrategyVote(
    strategy_name="GammaScalper",
    action=ConsensuAction.BUY,
    confidence=0.85,
    reasoning="Delta threshold exceeded",
    weight=1.0
)
```

### Consensus Calculation

The consensus score is calculated using **weighted voting**:

```
For each action (BUY, SELL, HOLD):
    action_score = Σ(weight_i × confidence_i) / Σ(weight_i)

final_action = argmax(action_score)
consensus_score = action_score[final_action]
```

### Execution Decision

Trade is executed **only if**:
1. `consensus_score >= threshold` (default 0.7)
2. `final_action != HOLD`

### Discordance Measurement

Discordance measures disagreement using **normalized Shannon entropy**:

```
H = -Σ(p_i × log₂(p_i))
discordance = H / log₂(n)

where:
  p_i = proportion of votes for action i
  n = number of unique actions voted on
```

- `discordance = 0.0`: Perfect agreement (all strategies vote same)
- `discordance = 1.0`: Maximum disagreement (votes evenly split)

## 🚀 Usage

### Basic Usage (Frontend)

```javascript
import { getFunctions, httpsCallable } from 'firebase/functions';

const functions = getFunctions();
const generateSignal = httpsCallable(functions, 'generate_consensus_signal');

// Generate consensus signal
const result = await generateSignal({
  symbol: 'SPY',
  consensus_threshold: 0.7,  // Optional: default 0.7
});

console.log(result.data);
// {
//   action: "BUY",
//   consensus_score: 0.85,
//   confidence: 0.88,
//   should_execute: true,
//   discordance: 0.15,
//   votes: [
//     { strategy_name: "GammaScalper", action: "BUY", confidence: 0.9 },
//     { strategy_name: "SentimentAlpha", action: "BUY", confidence: 0.85 },
//     { strategy_name: "FlowTrend", action: "HOLD", confidence: 0.6 }
//   ],
//   vote_summary: { BUY: 2, SELL: 0, HOLD: 1 },
//   reasoning: "Consensus: BUY with score 0.85..."
// }
```

### Advanced Usage: Custom Weights

```javascript
// Give more weight to historically better-performing strategies
const result = await generateSignal({
  symbol: 'SPY',
  consensus_threshold: 0.75,
  strategy_weights: {
    'GammaScalper': 2.0,      // 2x weight
    'SentimentAlpha': 1.5,    // 1.5x weight
    'FlowTrend': 1.0,         // 1x weight (default)
  }
});
```

### Active Strategy Selection

```javascript
// Only use specific strategies
const result = await generateSignal({
  symbol: 'SPY',
  active_strategies: ['GammaScalper', 'SentimentAlpha']
  // FlowTrend and others will be ignored
});
```

### Python SDK Usage

```python
from consensus_engine import ConsensusEngine
from firebase_admin import firestore

# Initialize
db = firestore.client()
engine = ConsensusEngine(
    consensus_threshold=0.7,
    strategy_weights={'GammaScalper': 2.0},
    db=db
)

# Generate consensus signal
result = await engine.generate_consensus_signal(
    market_data={
        "symbol": "SPY",
        "price": 450.0,
        "greeks": {...}
    },
    account_snapshot={
        "equity": "10000",
        "buying_power": "5000"
    },
    regime="SHORT_GAMMA",
    user_id="user123"
)

print(f"Action: {result.final_action.value}")
print(f"Consensus: {result.consensus_score:.2f}")
print(f"Should Execute: {result.should_execute}")
```

## 📁 Firestore Data Model

### Collections Created

#### 1. `consensusSignals` Collection

Stores every consensus decision for historical analysis:

```javascript
{
  final_action: "BUY",
  consensus_score: 0.85,
  confidence: 0.88,
  reasoning: "Consensus: BUY with score 0.85...",
  should_execute: true,
  discordance: 0.15,
  votes: [
    {
      strategy_name: "GammaScalper",
      action: "BUY",
      confidence: 0.9,
      reasoning: "Delta threshold exceeded",
      weight: 1.0
    },
    // ... more votes
  ],
  vote_summary: { BUY: 2, SELL: 0, HOLD: 1 },
  timestamp: Timestamp,
  user_id: "user123"
}
```

#### 2. `discordanceEvents` Collection

Logs high-discordance events (discordance > 0.5) for strategy performance analysis:

```javascript
{
  discordance: 0.75,
  final_action: "BUY",
  consensus_score: 0.55,
  vote_summary: { BUY: 2, SELL: 2 },  // Split vote
  votes: [...],
  should_execute: false,  // Below threshold
  timestamp: Timestamp,
  user_id: "user123",
  threshold: 0.7
}
```

**Use Cases for Discordance Tracking:**
- Identify strategies that frequently disagree with consensus
- Detect market regimes where strategies conflict
- Find opportunities to tune or disable underperforming strategies
- Audit decision quality over time

## 🎨 Adding New Strategies

To add a new strategy to the consensus ensemble:

### Step 1: Create Strategy File

Create a new file in `functions/strategies/`:

```python
# functions/strategies/my_custom_strategy.py

from .base_strategy import BaseStrategy, TradingSignal, SignalType

class MyCustomStrategy(BaseStrategy):
    """
    My custom trading strategy.
    """
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        # Your strategy logic here
        
        if some_condition:
            return TradingSignal(
                signal_type=SignalType.BUY,
                confidence=0.85,
                reasoning="My strategy says BUY because...",
                metadata={"custom_data": "value"}
            )
        else:
            return TradingSignal(
                signal_type=SignalType.HOLD,
                confidence=0.5,
                reasoning="Conditions not met"
            )
```

### Step 2: That's It!

The strategy loader will **automatically discover** your strategy. No registration needed.

Test it:

```javascript
const result = await generateSignal({
  symbol: 'SPY',
  active_strategies: ['MyCustomStrategy']
});
```

## 📈 Example Scenarios

### Scenario 1: Strong Consensus (Execute)

```
GammaScalper:    BUY  (confidence: 0.90)
SentimentAlpha:  BUY  (confidence: 0.85)
FlowTrend:       BUY  (confidence: 0.80)

→ Consensus Score: 0.85
→ Discordance: 0.0 (perfect agreement)
→ Should Execute: YES ✅
```

### Scenario 2: Weak Consensus (Do Not Execute)

```
GammaScalper:    BUY  (confidence: 0.60)
SentimentAlpha:  HOLD (confidence: 0.70)
FlowTrend:       SELL (confidence: 0.55)

→ Consensus Score: 0.62
→ Discordance: 0.85 (high disagreement)
→ Should Execute: NO ❌
→ Discordance event logged to Firestore
```

### Scenario 3: Weighted Vote

```
Weights: GammaScalper=2.0, SentimentAlpha=1.0

GammaScalper:    BUY  (confidence: 0.90, weight: 2.0) → score: 1.80
SentimentAlpha:  SELL (confidence: 0.85, weight: 1.0) → score: 0.85

Total weight: 3.0
BUY score:  1.80 / 3.0 = 0.60
SELL score: 0.85 / 3.0 = 0.28

→ Final Action: BUY
→ Consensus Score: 0.60
→ Should Execute: NO (below 0.7 threshold)
```

## 🔍 Monitoring & Analysis

### Query Firestore for Analytics

```javascript
// Find high-discordance events
const discordanceQuery = await db.collection('discordanceEvents')
  .where('discordance', '>', 0.7)
  .orderBy('timestamp', 'desc')
  .limit(10)
  .get();

// Analyze strategy performance
const votes = discordanceQuery.docs.flatMap(doc => doc.data().votes);
const strategyAccuracy = {};

votes.forEach(vote => {
  if (!strategyAccuracy[vote.strategy_name]) {
    strategyAccuracy[vote.strategy_name] = { correct: 0, total: 0 };
  }
  strategyAccuracy[vote.strategy_name].total++;
  // Add logic to track if vote was "correct" based on market outcome
});
```

### Dashboard Metrics

Key metrics to track:

1. **Consensus Rate**: Percentage of signals with consensus > threshold
2. **Average Discordance**: Lower is better
3. **Strategy Win Rate**: How often each strategy votes with the winning action
4. **Execution Rate**: Percentage of signals that result in actual trades

## 🛡️ Best Practices

### 1. Start with Equal Weights

Begin with all strategies having weight 1.0. Adjust based on historical performance.

### 2. Use High Threshold Initially

Start with `consensus_threshold = 0.8` to be conservative. Lower it as you gain confidence.

### 3. Monitor Discordance

High discordance (>0.6) indicates:
- Conflicting market signals
- Strategies needing tuning
- Possible regime change

### 4. Backtest Consensus Logic

Test consensus decisions against historical data to find optimal:
- Consensus threshold
- Strategy weights
- Active strategy combinations

### 5. Implement Strategy Timeouts

If a strategy takes too long to evaluate, add timeout handling:

```python
import asyncio

async def evaluate_with_timeout(strategy, timeout=5.0):
    try:
        return await asyncio.wait_for(
            strategy.evaluate(...),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        return TradingSignal(SignalType.HOLD, 0.0, "Timeout")
```

## 🧪 Testing

Run the comprehensive test suite:

```bash
pytest tests/test_consensus_engine.py -v
```

Test coverage includes:
- Vote normalization (TradingSignal and dict formats)
- Consensus calculation (unanimous, split, weighted)
- Discordance measurement
- Threshold enforcement
- Error handling and edge cases
- Firestore logging

## 🚨 Troubleshooting

### Issue: Strategy Not Discovered

**Problem**: Your strategy isn't showing up in consensus votes.

**Solutions**:
1. Ensure class inherits from `BaseStrategy`
2. Verify file is in `functions/strategies/` folder
3. Check for import errors: `from strategies import list_strategies; list_strategies()`

### Issue: Low Consensus Score

**Problem**: Consensus score always below threshold.

**Solutions**:
1. Lower the threshold temporarily
2. Check if strategies are too conservative (low confidence)
3. Review strategy logic for bugs
4. Consider removing strategies that always vote HOLD

### Issue: High Discordance

**Problem**: Discordance consistently above 0.7.

**Solutions**:
1. Review market regime - volatile conditions cause disagreement
2. Check if strategies are analyzing different timeframes
3. Consider tuning strategy parameters
4. Temporarily disable problematic strategies

## 📚 API Reference

### ConsensusEngine

```python
class ConsensusEngine:
    def __init__(
        self,
        consensus_threshold: float = 0.7,
        strategy_weights: Optional[Dict[str, float]] = None,
        db: Optional[firestore.Client] = None
    )
    
    async def generate_consensus_signal(
        self,
        market_data: Dict[str, Any],
        account_snapshot: Dict[str, Any],
        regime: Optional[str] = None,
        active_strategies: Optional[List[str]] = None,
        user_id: Optional[str] = None
    ) -> ConsensusResult
```

### StrategyVote

```python
@dataclass
class StrategyVote:
    strategy_name: str
    action: ConsensuAction
    confidence: float
    reasoning: str
    weight: float = 1.0
    metadata: Optional[Dict[str, Any]] = None
```

### ConsensusResult

```python
@dataclass
class ConsensusResult:
    final_action: ConsensuAction
    consensus_score: float
    confidence: float
    reasoning: str
    votes: List[StrategyVote]
    discordance: float
    should_execute: bool
    metadata: Optional[Dict[str, Any]] = None
```

## 🎓 Learn More

- [Base Strategy Protocol](./BASE_STRATEGY.md)
- [Gamma Scalper Implementation](../GAMMA_SCALPER_IMPLEMENTATION.md)
- [Risk Management](../PHASE3_RISK_MANAGEMENT_VERIFICATION.md)
- [Production Deployment](../PRODUCTION_DEPLOYMENT_GUIDE.md)

## 📞 Support

For issues or questions:
1. Check the troubleshooting section above
2. Review test cases in `tests/test_consensus_engine.py`
3. Examine Firestore `discordanceEvents` for insights
4. Open an issue with consensus signal logs

---

**Built with ❤️ for robust, ensemble-based trading decisions**
