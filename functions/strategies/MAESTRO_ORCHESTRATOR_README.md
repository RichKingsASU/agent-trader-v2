# MaestroOrchestrator - Performance-Based Agent Weighting Engine

## Overview

The `MaestroOrchestrator` is a sophisticated portfolio management system that dynamically adjusts capital allocation across specialized trading agents based on their historical performance using Sharpe Ratio analysis and Softmax normalization.

## Key Features

### 1. **Precision Financial Math**
- All calculations use `decimal.Decimal` for maximum precision
- No floating-point arithmetic in financial computations
- Only converts to float for `math.sqrt()` operation, then immediately back to Decimal

### 2. **Performance-Based Weighting**
- Queries Firestore `users/{uid}/tradeJournal/` for historical trades
- Calculates Sharpe Ratio for each agent (risk-adjusted returns)
- Uses Softmax normalization to ensure weights sum to 1.0

### 3. **Flexible Configuration**
- Configurable lookback period (default: 100 trades)
- Adjustable risk-free rate (default: 4% annually)
- Optional floor weight for negative-Sharpe agents (default: 5%)
- Strict performance enforcement mode (zero weight for negative Sharpe)

### 4. **BaseStrategy Integration**
- Follows the same lifecycle hooks as other strategies
- Compatible with existing risk circuit breakers
- Returns standardized `TradingSignal` objects

## Architecture

### Data Flow

```
1. Fetch Trades
   └─> users/{uid}/tradeJournal/ (per agent, last N trades)

2. Calculate Returns
   └─> return = (realized_pnl / entry_capital) * 100

3. Compute Sharpe Ratios
   └─> Sharpe = (mean_return - risk_free_rate) / std_dev

4. Apply Softmax Normalization
   └─> weight_i = exp(sharpe_i) / Σ(exp(sharpe_j))

5. Return Weights
   └─> Dict[agent_id, weight] (sum = 1.0)
```

### Mathematical Formulas

#### Daily Return Calculation
```
return = (realized_pnl / (entry_price × quantity)) × 100
```

#### Sharpe Ratio
```
Sharpe = (μ_returns - rf_daily) / σ_returns

where:
  μ_returns = mean daily return (%)
  rf_daily = (annual_rf / 252) × 100  (convert to daily %)
  σ_returns = sample standard deviation of returns
```

#### Softmax Normalization
```
weight_i = exp(sharpe_i - max(sharpe)) / Σ(exp(sharpe_j - max(sharpe)))
```

Note: We subtract max(sharpe) for numerical stability.

## Usage

### Basic Setup

```python
from firebase_admin import firestore
from strategies.maestro_orchestrator import MaestroOrchestrator

# Initialize with default config
maestro = MaestroOrchestrator()

# Or customize configuration
config = {
    'agent_ids': [
        'WhaleFlowAgent',
        'SentimentAgent',
        'GammaScalper',
        'SectorRotation'
    ],
    'lookback_trades': 100,
    'risk_free_rate': '0.04',  # 4% annual
    'min_floor_weight': '0.05',  # 5% floor for recovery
    'enforce_performance': False  # Allow negative Sharpe agents
}

maestro = MaestroOrchestrator(config=config)
```

### Calculate Agent Weights

```python
# Get weights for a specific user
user_id = 'user123'
weights = maestro.calculate_agent_weights(user_id)

# Example output:
# {
#     'WhaleFlowAgent': Decimal('0.45'),
#     'SentimentAgent': Decimal('0.30'),
#     'GammaScalper': Decimal('0.20'),
#     'SectorRotation': Decimal('0.05')
# }
```

### Integration with Strategy Evaluation

```python
# Use in standard strategy lifecycle
account_snapshot = {
    'user_id': 'user123',
    'equity': '100000',
    'buying_power': '50000',
    'cash': '50000',
    'positions': []
}

market_data = {
    'symbol': 'SPY',
    'price': 450.0
}

signal = maestro.evaluate(market_data, account_snapshot)

# Signal includes weights in metadata
weights = signal.metadata['weights']
print(f"Top performer: {max(weights.items(), key=lambda x: x[1])}")
```

## Configuration Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_ids` | List[str] | `['WhaleFlowAgent', 'SentimentAgent', 'GammaScalper', 'SectorRotation']` | List of agent identifiers to track |
| `lookback_trades` | int | `100` | Number of recent trades to analyze per agent |
| `risk_free_rate` | str/Decimal | `'0.04'` | Annual risk-free rate for Sharpe calculation (4%) |
| `min_floor_weight` | str/Decimal | `'0.05'` | Minimum weight for negative Sharpe agents (5%) |
| `enforce_performance` | bool | `False` | If True, assign 0 weight to negative Sharpe agents |

## Firestore Schema Requirements

### tradeJournal Collection

The Maestro queries `users/{uid}/tradeJournal/{tradeId}` with the following expected fields:

```typescript
interface TradeJournalEntry {
  trade_id: string;
  user_id: string;
  agent_id: string;  // REQUIRED: e.g., 'WhaleFlowAgent'
  symbol: string;
  side: 'BUY' | 'SELL';
  entry_price: string;  // Decimal as string
  exit_price: string;
  quantity: string;  // Decimal as string
  realized_pnl: string;  // Decimal as string
  created_at: Timestamp;
  closed_at: Timestamp;  // REQUIRED for ordering
  // ... other fields
}
```

**Critical Fields:**
- `agent_id`: Must match entries in `config.agent_ids`
- `closed_at`: Used for ordering (most recent first)
- `realized_pnl`: Actual P&L in dollars
- `entry_price`, `quantity`: Used to calculate return percentage

### Firestore Index Required

Create a composite index for efficient queries:

```json
{
  "collectionGroup": "tradeJournal",
  "queryScope": "COLLECTION",
  "fields": [
    {
      "fieldPath": "agent_id",
      "order": "ASCENDING"
    },
    {
      "fieldPath": "closed_at",
      "order": "DESCENDING"
    }
  ]
}
```

## Example Output

### Console Logs

```
INFO: Processing agent 'WhaleFlowAgent'...
INFO: Fetched 100 trades for agent 'WhaleFlowAgent'
INFO: Agent 'WhaleFlowAgent': 100 returns, mean=2.3450%, Sharpe=1.8734

INFO: Processing agent 'SentimentAgent'...
INFO: Fetched 95 trades for agent 'SentimentAgent'
INFO: Agent 'SentimentAgent': 95 returns, mean=1.5620%, Sharpe=1.2156

INFO: Processing agent 'GammaScalper'...
INFO: Fetched 80 trades for agent 'GammaScalper'
INFO: Agent 'GammaScalper': 80 returns, mean=-0.5430%, Sharpe=-0.4321
INFO: Agent 'GammaScalper' has negative Sharpe -0.4321, assigning floor weight 0.05

============================================================
MAESTRO ORCHESTRATOR - FINAL WEIGHTS
============================================================
WhaleFlowAgent      :  50.23% (Sharpe:  1.8734)
SentimentAgent      :  35.42% (Sharpe:  1.2156)
SectorRotation      :   9.35% (Sharpe:  0.3421)
GammaScalper        :   5.00% (Sharpe: -0.4321)
============================================================
```

## Performance Considerations

### Query Optimization

- Uses Firestore `limit()` to fetch only required trades
- Leverages composite index for efficient `where` + `order_by`
- Typical query time: 50-200ms per agent (depending on index warmth)

### Computation Complexity

- **Time Complexity**: O(N × M) where N = number of agents, M = trades per agent
- **Space Complexity**: O(N × M) for trade storage
- Typical execution time: 200-500ms for 4 agents × 100 trades each

### Caching Strategy

Consider implementing caching for production use:

```python
# Cache weights for 5 minutes
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=100)
def get_cached_weights(user_id: str, cache_key: str) -> Dict[str, Decimal]:
    return maestro.calculate_agent_weights(user_id)

# Cache key changes every 5 minutes
cache_key = str(int(datetime.now().timestamp() / 300))
weights = get_cached_weights(user_id, cache_key)
```

## Edge Cases

### 1. No Trade History

If an agent has no trades in the journal:
- Assigned Sharpe Ratio of 0
- Receives floor weight (or 0 if `enforce_performance=True`)

### 2. All Negative Sharpe Ratios

If all agents have negative Sharpe:
- With `enforce_performance=False`: Equal floor weights
- With `enforce_performance=True`: All receive 0 weight, warning logged

### 3. Insufficient Data

If an agent has < 2 trades:
- Sharpe Ratio set to 0 (need at least 2 returns for std dev)

### 4. Numerical Stability

- Softmax uses max subtraction to prevent overflow
- Variance calculation uses sample variance (n-1 denominator)
- All Decimal operations have 28 digits of precision

## Testing

Run the comprehensive test suite:

```bash
cd functions/strategies
python -m pytest test_maestro_orchestrator.py -v

# Or with unittest
python test_maestro_orchestrator.py
```

### Test Coverage

- ✅ Initialization and configuration
- ✅ Daily return calculation
- ✅ Sharpe Ratio computation
- ✅ Softmax normalization
- ✅ Negative Sharpe handling (both modes)
- ✅ Firestore query mocking
- ✅ End-to-end weight calculation
- ✅ Decimal precision verification
- ✅ Edge cases (no data, invalid data, etc.)

## Integration Example

### Using Maestro with Execution Engine

```python
from strategies.maestro_orchestrator import MaestroOrchestrator
from strategies.gamma_scalper import GammaScalper
from strategies.sector_rotation import SectorRotation

# Initialize Maestro and agents
maestro = MaestroOrchestrator()
agents = {
    'WhaleFlowAgent': WhaleFlowStrategy(),
    'SentimentAgent': SentimentStrategy(),
    'GammaScalper': GammaScalper(),
    'SectorRotation': SectorRotation()
}

# Get current weights
weights = maestro.calculate_agent_weights(user_id)

# Allocate capital based on weights
total_capital = Decimal('100000')

for agent_id, weight in weights.items():
    agent = agents[agent_id]
    agent_capital = total_capital * weight
    
    # Run agent with allocated capital
    signal = agent.evaluate(market_data, account_snapshot)
    
    if signal.signal_type == SignalType.BUY:
        # Scale position size by weight
        position_size = agent_capital * Decimal(str(signal.confidence))
        # Execute trade...
```

## Troubleshooting

### Issue: "No trades found for agent"

**Cause**: Agent ID doesn't match any entries in `tradeJournal` collection.

**Solution**: 
1. Verify `agent_id` field exists in journal entries
2. Check spelling matches exactly (case-sensitive)
3. Ensure trades have `closed_at` timestamp

### Issue: "Weights don't sum to 1.0"

**Cause**: Numerical precision issues in Softmax calculation.

**Solution**: Already handled by automatic renormalization in code. If you see this warning in logs, it's automatically corrected.

### Issue: "Missing Firestore index"

**Cause**: Composite index not created for `agent_id` + `closed_at`.

**Solution**:
```bash
# Deploy index via Firebase CLI
firebase deploy --only firestore:indexes
```

Or create manually in Firebase Console:
- Collection: `tradeJournal`
- Fields: `agent_id` (ASC), `closed_at` (DESC)

## Future Enhancements

### Planned Features

1. **Time-Weighted Sharpe**: Give more weight to recent trades
2. **Multi-Period Analysis**: Calculate Sharpe over multiple timeframes
3. **Drawdown Penalty**: Factor in maximum drawdown into weights
4. **Kelly Criterion**: Optional Kelly-based position sizing
5. **Volatility Targeting**: Adjust weights to target portfolio volatility

### Research Ideas

- **ML-Based Weighting**: Use XGBoost to predict agent performance
- **Regime-Aware Allocation**: Adjust weights based on market regime
- **Correlation Matrix**: Account for agent strategy correlation
- **Dynamic Rebalancing**: Trigger weight recalculation on performance drift

## References

- [Sharpe Ratio](https://en.wikipedia.org/wiki/Sharpe_ratio) - Risk-adjusted return metric
- [Softmax Function](https://en.wikipedia.org/wiki/Softmax_function) - Normalization for probability distributions
- [Python Decimal Module](https://docs.python.org/3/library/decimal.html) - Arbitrary precision arithmetic

## License

This module is part of the trading platform and subject to the repository's license.

---

**Version**: 1.0.0  
**Last Updated**: December 30, 2025  
**Author**: Cursor Agent  
**Maintainer**: Platform Team
