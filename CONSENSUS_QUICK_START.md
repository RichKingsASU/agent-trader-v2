# Consensus Engine Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Step 1: Deploy the Consensus Function

The consensus engine is already integrated into your Firebase Functions. Deploy it:

```bash
cd functions
firebase deploy --only functions:generate_consensus_signal
```

### Step 2: Call from Frontend

```javascript
import { getFunctions, httpsCallable } from 'firebase/functions';

const functions = getFunctions();
const generateConsensusSignal = httpsCallable(functions, 'generate_consensus_signal');

// Generate a consensus signal
try {
  const result = await generateConsensusSignal({
    symbol: 'SPY',
    consensus_threshold: 0.7  // Optional: default is 0.7
  });
  
  console.log('Consensus Result:', result.data);
  // {
  //   action: "BUY",
  //   consensus_score: 0.85,
  //   should_execute: true,
  //   votes: [...],
  //   discordance: 0.15
  // }
  
  if (result.data.should_execute) {
    console.log(`✅ Execute ${result.data.action} with ${result.data.consensus_score * 100}% consensus`);
  } else {
    console.log(`⏸️ No consensus: score=${result.data.consensus_score}, threshold=0.7`);
  }
  
} catch (error) {
  console.error('Error:', error);
}
```

### Step 3: View Results in Firestore

Navigate to your Firestore console and check these collections:

1. **`consensusSignals`**: All consensus decisions
2. **`discordanceEvents`**: High-disagreement events
3. **`tradingSignals`**: Individual signal logs

### Step 4: Add Your Own Strategy (Optional)

Create a new file in `functions/strategies/`:

```python
# functions/strategies/my_strategy.py

from .base_strategy import BaseStrategy, TradingSignal, SignalType

class MyStrategy(BaseStrategy):
    """My custom strategy"""
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        # Your logic here
        price = market_data.get('price', 0)
        
        if price > 450:
            return TradingSignal(
                signal_type=SignalType.BUY,
                confidence=0.8,
                reasoning="Price above 450"
            )
        
        return TradingSignal(
            signal_type=SignalType.HOLD,
            confidence=0.5,
            reasoning="Waiting for better entry"
        )
```

Redeploy:
```bash
firebase deploy --only functions:generate_consensus_signal
```

Your strategy will automatically be included in consensus voting!

## 📊 Example: Complete React Component

```tsx
import React, { useState } from 'react';
import { getFunctions, httpsCallable } from 'firebase/functions';

export default function ConsensusSignalButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  
  const generateSignal = async () => {
    setLoading(true);
    
    try {
      const functions = getFunctions();
      const consensusSignal = httpsCallable(functions, 'generate_consensus_signal');
      
      const response = await consensusSignal({
        symbol: 'SPY',
        consensus_threshold: 0.7,
        // Optional: use only specific strategies
        // active_strategies: ['GammaScalper', 'SentimentAlpha']
      });
      
      setResult(response.data);
    } catch (error) {
      console.error('Error generating signal:', error);
      alert('Failed to generate signal: ' + error.message);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="p-4">
      <button
        onClick={generateSignal}
        disabled={loading}
        className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
      >
        {loading ? 'Generating...' : 'Generate Consensus Signal'}
      </button>
      
      {result && (
        <div className="mt-4 p-4 border rounded">
          <h3 className="font-bold text-lg mb-2">
            Action: {result.action}
            {result.should_execute ? ' ✅' : ' ⏸️'}
          </h3>
          
          <div className="space-y-2">
            <div>
              <span className="font-semibold">Consensus Score:</span> {(result.consensus_score * 100).toFixed(1)}%
            </div>
            
            <div>
              <span className="font-semibold">Confidence:</span> {(result.confidence * 100).toFixed(1)}%
            </div>
            
            <div>
              <span className="font-semibold">Discordance:</span> {(result.discordance * 100).toFixed(1)}%
              {result.discordance > 0.5 && <span className="ml-2 text-yellow-600">⚠️ High disagreement</span>}
            </div>
            
            <div>
              <span className="font-semibold">Vote Summary:</span>
              <ul className="ml-4 mt-1">
                {Object.entries(result.vote_summary).map(([action, count]) => (
                  <li key={action}>{action}: {count}</li>
                ))}
              </ul>
            </div>
            
            <div>
              <span className="font-semibold">Should Execute:</span> {result.should_execute ? 'YES' : 'NO'}
            </div>
            
            <details className="mt-2">
              <summary className="cursor-pointer font-semibold">Reasoning</summary>
              <p className="mt-2 text-sm text-gray-600">{result.reasoning}</p>
            </details>
            
            <details className="mt-2">
              <summary className="cursor-pointer font-semibold">Individual Votes ({result.votes.length})</summary>
              <ul className="mt-2 space-y-2">
                {result.votes.map((vote, idx) => (
                  <li key={idx} className="text-sm p-2 bg-gray-50 rounded">
                    <div className="font-semibold">{vote.strategy_name}</div>
                    <div>Action: {vote.action}</div>
                    <div>Confidence: {(vote.confidence * 100).toFixed(1)}%</div>
                    <div className="text-xs text-gray-600 mt-1">{vote.reasoning}</div>
                  </li>
                ))}
              </ul>
            </details>
          </div>
        </div>
      )}
    </div>
  );
}
```

## 🎯 Common Use Cases

### Use Case 1: Conservative Trading (High Threshold)

Only trade when strategies strongly agree:

```javascript
const result = await generateConsensusSignal({
  symbol: 'SPY',
  consensus_threshold: 0.9  // Require 90% consensus
});
```

### Use Case 2: Weighted Strategies

Give more weight to strategies with better historical performance:

```javascript
const result = await generateConsensusSignal({
  symbol: 'SPY',
  strategy_weights: {
    'GammaScalper': 2.0,      // Best performer: 2x weight
    'SentimentAlpha': 1.5,    // Good: 1.5x weight
    'FlowTrend': 0.5,         // Underperforming: 0.5x weight
  }
});
```

### Use Case 3: Strategy A/B Testing

Test different strategy combinations:

```javascript
// Test Group A
const resultA = await generateConsensusSignal({
  symbol: 'SPY',
  active_strategies: ['GammaScalper', 'SentimentAlpha']
});

// Test Group B
const resultB = await generateConsensusSignal({
  symbol: 'SPY',
  active_strategies: ['FlowTrend', 'CongressionalAlpha']
});

// Compare consensus scores
console.log('Group A consensus:', resultA.consensus_score);
console.log('Group B consensus:', resultB.consensus_score);
```

## 🔍 Monitoring Dashboard Example

```javascript
// Fetch recent consensus signals
const recentSignals = await db.collection('consensusSignals')
  .orderBy('timestamp', 'desc')
  .limit(50)
  .get();

// Calculate metrics
const signals = recentSignals.docs.map(doc => doc.data());

const metrics = {
  totalSignals: signals.length,
  executedSignals: signals.filter(s => s.should_execute).length,
  averageConsensus: signals.reduce((sum, s) => sum + s.consensus_score, 0) / signals.length,
  averageDiscordance: signals.reduce((sum, s) => sum + s.discordance, 0) / signals.length,
  actionBreakdown: {
    BUY: signals.filter(s => s.final_action === 'BUY').length,
    SELL: signals.filter(s => s.final_action === 'SELL').length,
    HOLD: signals.filter(s => s.final_action === 'HOLD').length,
  }
};

console.log('Consensus Metrics:', metrics);
```

## 📈 Performance Analysis

Query high-discordance events to find strategy issues:

```javascript
const discordanceEvents = await db.collection('discordanceEvents')
  .where('discordance', '>', 0.7)
  .orderBy('timestamp', 'desc')
  .limit(10)
  .get();

discordanceEvents.forEach(doc => {
  const event = doc.data();
  console.log(`
    High Discordance Event:
    - Discordance: ${(event.discordance * 100).toFixed(1)}%
    - Final Action: ${event.final_action}
    - Vote Split: ${JSON.stringify(event.vote_summary)}
    - Timestamp: ${event.timestamp.toDate()}
  `);
  
  // Identify problematic strategies
  event.votes.forEach(vote => {
    if (vote.action !== event.final_action) {
      console.log(`  ⚠️ ${vote.strategy_name} dissented with ${vote.action}`);
    }
  });
});
```

## 🧪 Testing

Test the consensus engine locally:

```bash
cd /workspace
pytest tests/test_consensus_engine.py -v
```

All 26 tests should pass ✅

## 📚 Next Steps

1. **Read the Full Documentation**: [`docs/CONSENSUS_ENGINE.md`](./docs/CONSENSUS_ENGINE.md)
2. **Add Custom Strategies**: Create files in `functions/strategies/`
3. **Monitor Discordance**: Review Firestore `discordanceEvents` collection
4. **Tune Weights**: Adjust `strategy_weights` based on performance
5. **Backtest**: Test consensus decisions against historical data

## 🎉 You're Ready!

The consensus engine is now running and will:
- ✅ Automatically discover all your strategies
- ✅ Calculate weighted consensus scores
- ✅ Only execute when consensus > threshold
- ✅ Log discordance for analysis
- ✅ Provide full transparency into decision-making

Happy trading! 🚀
