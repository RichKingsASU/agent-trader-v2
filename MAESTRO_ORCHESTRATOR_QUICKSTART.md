# MaestroOrchestrator Quick Start Guide

## 🚀 Get Started in 5 Minutes

The **MaestroOrchestrator** dynamically adjusts sub-agent weights based on their historical performance using Sharpe Ratios and Softmax normalization.

---

## Prerequisites

1. **Firebase Admin SDK** installed and initialized
2. **Trade Journal** populated with agent-specific trades
3. **Firestore Index** deployed (see below)

---

## Step 1: Deploy Firestore Index

```bash
# Deploy the required composite index
firebase deploy --only firestore:indexes
```

This creates an index on `tradeJournal` for:
- `agent_id` (ASCENDING)
- `closed_at` (DESCENDING)

---

## Step 2: Ensure Trade Data Has `agent_id`

Each trade in `users/{uid}/tradeJournal/{tradeId}` must have:

```json
{
  "trade_id": "trade_12345",
  "user_id": "user123",
  "agent_id": "WhaleFlowAgent",  // ← REQUIRED
  "symbol": "AAPL",
  "entry_price": "150.25",
  "quantity": "100",
  "realized_pnl": "525.00",
  "closed_at": "2025-12-30T10:00:00Z"  // ← REQUIRED
}
```

---

## Step 3: Basic Usage

```python
from strategies import MaestroOrchestrator

# Initialize with defaults
maestro = MaestroOrchestrator()

# Calculate weights for a user
weights = maestro.calculate_agent_weights('user123')

# Returns:
# {
#     'WhaleFlowAgent': Decimal('0.45'),    # 45% allocation
#     'SentimentAgent': Decimal('0.30'),    # 30% allocation
#     'GammaScalper': Decimal('0.20'),      # 20% allocation
#     'SectorRotation': Decimal('0.05')     # 5% allocation
# }

print(f"Top performer: {max(weights.items(), key=lambda x: x[1])}")
```

---

## Step 4: Custom Configuration

```python
config = {
    # Which agents to track
    'agent_ids': [
        'WhaleFlowAgent',
        'SentimentAgent',
        'GammaScalper',
        'SectorRotation'
    ],
    
    # Analyze last 150 trades per agent (default: 100)
    'lookback_trades': 150,
    
    # Annual risk-free rate for Sharpe calculation (default: 4%)
    'risk_free_rate': '0.04',
    
    # Minimum weight for negative Sharpe agents (default: 5%)
    'min_floor_weight': '0.05',
    
    # Strict mode: zero weight for negative Sharpe (default: False)
    'enforce_performance': False
}

maestro = MaestroOrchestrator(config=config)
```

---

## Step 5: Integration with Strategy Evaluation

```python
# Use in standard BaseStrategy lifecycle
account_snapshot = {
    'user_id': 'user123',
    'equity': '100000',
    'buying_power': '50000'
}

market_data = {
    'symbol': 'SPY',
    'price': 450.0
}

# Get signal with weights in metadata
signal = maestro.evaluate(market_data, account_snapshot)

# Extract weights
weights = signal.metadata['weights']

# Allocate capital
total_capital = Decimal('100000')
for agent_id, weight in weights.items():
    allocation = total_capital * weight
    print(f"{agent_id}: ${float(allocation):,.2f}")
```

---

## Expected Output

```
============================================================
MAESTRO ORCHESTRATOR - FINAL WEIGHTS
============================================================
WhaleFlowAgent      :  45.23% (Sharpe:  1.8734)
SentimentAgent      :  30.42% (Sharpe:  1.2156)
SectorRotation      :  19.35% (Sharpe:  0.8421)
GammaScalper        :   5.00% (Sharpe: -0.4321)
============================================================
```

---

## Key Concepts

### Sharpe Ratio
**Formula**: `(mean_return - risk_free_rate) / std_dev_return`

- Measures risk-adjusted returns
- Higher Sharpe = better risk-adjusted performance
- Default risk-free rate: 4% annual (converted to daily)

### Softmax Normalization
**Formula**: `weight_i = exp(sharpe_i) / Σ(exp(sharpe_j))`

- Converts Sharpe Ratios into probability distribution
- Weights always sum to 1.0 (100%)
- Higher Sharpe agents get exponentially more weight

### Negative Sharpe Handling

**Mode 1: Recovery Mode** (`enforce_performance=False`, default)
- Agents with negative Sharpe get floor weight (default: 5%)
- Allows underperforming agents to "recover"
- More forgiving, maintains diversification

**Mode 2: Strict Mode** (`enforce_performance=True`)
- Agents with negative Sharpe get 0% allocation
- Only profitable agents receive capital
- More aggressive performance filtering

---

## Troubleshooting

### Issue: "No trades found for agent"
**Solution**: Ensure trade journal has `agent_id` field matching configured agents.

### Issue: "Firestore index not found"
**Solution**: Run `firebase deploy --only firestore:indexes`

### Issue: "Weights don't sum to 1.0"
**Solution**: Already handled automatically - warning will appear in logs if renormalization occurs.

---

## Configuration Examples

### Conservative (More Diversification)
```python
config = {
    'min_floor_weight': '0.10',      # 10% floor
    'enforce_performance': False,     # Allow recovery
    'lookback_trades': 200           # Longer history
}
```

### Aggressive (Performance-Focused)
```python
config = {
    'min_floor_weight': '0.00',      # No floor
    'enforce_performance': True,      # Strict enforcement
    'lookback_trades': 50            # Recent performance only
}
```

### Balanced (Default)
```python
config = {
    'min_floor_weight': '0.05',      # 5% floor
    'enforce_performance': False,     # Allow recovery
    'lookback_trades': 100           # Standard lookback
}
```

---

## Performance Tips

### 1. Cache Weights
```python
from functools import lru_cache
from datetime import datetime

@lru_cache(maxsize=100)
def get_cached_weights(user_id: str, cache_key: str):
    return maestro.calculate_agent_weights(user_id)

# Cache key changes every 5 minutes
cache_key = str(int(datetime.now().timestamp() / 300))
weights = get_cached_weights(user_id, cache_key)
```

### 2. Reduce Lookback Period
```python
# Faster queries, but less historical data
config = {'lookback_trades': 50}
```

### 3. Batch Processing
```python
# Process multiple users in parallel
import concurrent.futures

user_ids = ['user1', 'user2', 'user3']
with concurrent.futures.ThreadPoolExecutor() as executor:
    weights_map = dict(zip(
        user_ids,
        executor.map(maestro.calculate_agent_weights, user_ids)
    ))
```

---

## Next Steps

1. ✅ Deploy Firestore index
2. ✅ Verify `agent_id` in trade journal
3. ✅ Test with `example_maestro_usage.py`
4. ✅ Integrate with execution engine
5. ✅ Monitor performance in production

---

## Documentation

- **Full Documentation**: `MAESTRO_ORCHESTRATOR_README.md`
- **Implementation Summary**: `MAESTRO_ORCHESTRATOR_IMPLEMENTATION_SUMMARY.md`
- **Usage Examples**: `example_maestro_usage.py`
- **Unit Tests**: `test_maestro_orchestrator.py`
- **Verification**: `verify_maestro_implementation.py`

---

## Support

For issues or questions:
1. Check `MAESTRO_ORCHESTRATOR_README.md` for troubleshooting
2. Run verification: `python3 verify_maestro_implementation.py`
3. Review examples: `python3 example_maestro_usage.py`

---

**Status**: ✅ Production Ready  
**Version**: 1.0.0  
**Last Updated**: December 30, 2025
