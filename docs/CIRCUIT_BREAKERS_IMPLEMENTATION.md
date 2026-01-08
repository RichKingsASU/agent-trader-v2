# Smart Risk Circuit Breakers Implementation

## Overview

This document describes the implementation of Smart Risk Circuit Breakers in the BaseStrategy execution loop. The circuit breakers provide automated risk management to protect user capital during adverse market conditions.

## Three Circuit Breakers

### 1. Daily Loss Limit (-2%)

**Purpose**: Prevent catastrophic losses by stopping trading when daily PnL drops below -2%.

**Behavior**:
- Monitors real-time PnL for each user
- Calculates percentage loss relative to starting equity
- Triggers when loss reaches or exceeds -2%
- **Action**: Immediately switches ALL active strategies for the user to SHADOW_MODE
- **Notification**: Sends critical alert to user

**Implementation**:
```python
should_trigger, event = circuit_breaker_manager.check_daily_loss_limit(
    tenant_id=tenant_id,
    user_id=user_id,
    strategy_id=strategy_id,
    trades=trades_today,
    starting_equity=starting_equity,
)
```

### 2. VIX Guard (VIX > 30)

**Purpose**: Reduce position sizing during high market volatility to preserve capital.

**Behavior**:
- Fetches current VIX (CBOE Volatility Index) value
- Checks if VIX exceeds threshold of 30
- Triggers on elevated volatility
- **Action**: Reduces allocation parameter by 50% for all incoming signals
- **Notification**: Sends warning alert to user

**Implementation**:
```python
adjusted_allocation, event = circuit_breaker_manager.check_vix_guard(
    allocation=original_allocation,
)
```

**VIX Data Ingestion**:
- Scheduled Cloud Function runs every 5 minutes
- Fetches VIX from Alpaca (primary) or Yahoo Finance (fallback)
- Stores in Firestore at `systemStatus/vix_data`
- 5-minute cache for performance

### 3. Concentration Check (> 20%)

**Purpose**: Maintain portfolio diversification by preventing over-concentration in single positions.

**Behavior**:
- Calculates position value as percentage of total portfolio
- Checks before executing BUY signals
- Triggers if ticker already represents > 20% of portfolio
- **Action**: Downgrades BUY signal to HOLD
- **Notification**: Sends warning alert to user

**Implementation**:
```python
adjusted_action, event = circuit_breaker_manager.check_concentration(
    ticker=ticker,
    signal_action=signal_action,
    positions=positions_dict,
    total_portfolio_value=total_portfolio_value,
)
```

## Architecture

### Components

```
backend/risk/
├── __init__.py                   # Module exports
├── circuit_breakers.py           # Core circuit breaker logic
├── vix_ingestion.py              # VIX data fetching service
├── notifications.py              # User notification service
├── strategy_integration.py       # Strategy wrapper logic
└── base_strategy_wrapper.py      # Main integration point

functions/
└── scheduled_vix_ingestion.py    # Cloud Function for VIX updates

tests/
└── test_circuit_breakers.py      # Comprehensive test suite
```

### Data Flow

```
1. Strategy Evaluation Request
   ↓
2. Evaluate Strategy (BaseStrategy.evaluate())
   ↓
3. Apply Circuit Breakers
   ├─→ Daily Loss Limit Check
   ├─→ VIX Guard Check
   └─→ Concentration Check
   ↓
4. Adjust Signal (if triggered)
   ↓
5. Send Notifications
   ↓
6. Store Event Audit Trail
   ↓
7. Return Adjusted Signal
```

## Integration with BaseStrategy

### Option 1: Wrapper Function (Recommended)

Use the provided wrapper function that handles all circuit breaker logic:

```python
from backend.risk.base_strategy_wrapper import evaluate_strategy_with_circuit_breakers

# In your strategy execution loop
signal = await evaluate_strategy_with_circuit_breakers(
    strategy=strategy_instance,
    market_data=market_data,
    account_snapshot=account_snapshot,
    regime=regime,
    user_id=user_id,
    tenant_id=tenant_id,
    strategy_id=strategy_id,
    db=firestore_client,
    trades_today=trades_today,  # Optional
    starting_equity=starting_equity,  # Optional
)
```

### Option 2: Manual Integration

For more control, use the components directly:

```python
from backend.risk.circuit_breakers import CircuitBreakerManager
from backend.risk.notifications import NotificationService
from backend.risk.strategy_integration import StrategyCircuitBreakerWrapper

# Initialize services
notification_service = NotificationService(db_client=db)
circuit_breaker_manager = CircuitBreakerManager(
    db_client=db,
    notification_service=notification_service,
)
wrapper = StrategyCircuitBreakerWrapper(
    circuit_breaker_manager=circuit_breaker_manager,
    notification_service=notification_service,
)

# Evaluate strategy
original_signal = strategy.evaluate(market_data, account_snapshot)

# Apply circuit breakers
adjusted_signal = await wrapper.evaluate_with_circuit_breakers(
    tenant_id=tenant_id,
    user_id=user_id,
    strategy_id=strategy_id,
    signal=original_signal,
    account_snapshot=account_snapshot,
    trades_today=trades_today,
    starting_equity=starting_equity,
)
```

## Configuration

### Circuit Breaker Thresholds

Thresholds are defined in `backend/risk/circuit_breakers.py`:

```python
class CircuitBreakerManager:
    # Circuit breaker thresholds
    DAILY_LOSS_THRESHOLD = -0.02  # -2%
    VIX_THRESHOLD = 30.0
    CONCENTRATION_THRESHOLD = 0.20  # 20%
    ALLOCATION_REDUCTION_FACTOR = 0.5  # 50% reduction
```

To customize thresholds, modify these class variables or pass them in the constructor.

### VIX Ingestion Schedule

VIX data is fetched every 5 minutes during market hours:

```python
@scheduler_fn.on_schedule(
    schedule="*/5 * * * *",  # Every 5 minutes
    timezone="America/New_York",
)
```

## Firestore Schema

### VIX Data

**Path**: `systemStatus/vix_data`

```json
{
  "current_value": 32.5,
  "updated_at": "2025-12-30T10:30:00Z",
  "source": "alpaca"
}
```

**History**: `systemStatus/vix_data/history/{auto_id}`

```json
{
  "value": 32.5,
  "timestamp": "2025-12-30T10:30:00Z"
}
```

### Circuit Breaker Events

**Path**: `users/{userId}/circuit_breaker_events/{auto_id}`

```json
{
  "breaker_type": "daily_loss_limit",
  "timestamp": "2025-12-30T14:15:00Z",
  "user_id": "user123",
  "tenant_id": "tenant456",
  "strategy_id": "gamma_scalper",
  "severity": "critical",
  "message": "Daily loss limit breached: -2.5% (-$250). Switching to SHADOW_MODE.",
  "metadata": {
    "realized_pnl": -250.0,
    "pnl_percentage": -0.025,
    "starting_equity": 10000.0,
    "threshold": -0.02
  }
}
```

### Notifications

**Path**: `users/{userId}/notifications/{auto_id}`

```json
{
  "title": "🚨 Daily Loss Limit Breached",
  "message": "Your strategy 'gamma_scalper' has reached the daily loss limit...",
  "severity": "critical",
  "created_at": "2025-12-30T14:15:00Z",
  "read": false,
  "metadata": {
    "tenant_id": "tenant456",
    "strategy_id": "gamma_scalper",
    "pnl_percentage": -0.025,
    "pnl_amount": -250.0,
    "action_taken": "switched_to_shadow_mode"
  }
}
```

## Testing

Run the comprehensive test suite:

```bash
pytest tests/test_circuit_breakers.py -v
```

### Test Coverage

- Daily Loss Limit:
  - ✅ No trigger with profit
  - ✅ Trigger with -2% loss
  - ✅ No trigger with -1% loss (below threshold)

- VIX Guard:
  - ✅ No trigger with VIX < 30
  - ✅ Trigger with VIX > 30
  - ✅ Handle missing VIX data gracefully

- Concentration Check:
  - ✅ No trigger below 20% concentration
  - ✅ Trigger above 20% concentration
  - ✅ Only applies to BUY signals
  - ✅ Doesn't affect SELL or HOLD signals

- Event Handling:
  - ✅ Store events in Firestore
  - ✅ Send notifications
  - ✅ Switch strategies to shadow mode

## Deployment

### 1. Deploy VIX Ingestion Function

```bash
# Deploy to Cloud Functions
cd functions
firebase deploy --only functions:ingest_vix_data
firebase deploy --only functions:initialize_daily_vix
```

### 2. Update Strategy Execution

Modify `functions/main.py` to use the circuit breaker wrapper:

```python
# Before (without circuit breakers)
signal = await strategy.evaluate(market_data, account_snapshot)

# After (with circuit breakers)
from backend.risk.base_strategy_wrapper import evaluate_strategy_with_circuit_breakers

signal = await evaluate_strategy_with_circuit_breakers(
    strategy=strategy,
    market_data=market_data,
    account_snapshot=account_snapshot,
    user_id=user_id,
    tenant_id=tenant_id,
    strategy_id=strategy_id,
    db=db,
)
```

### 3. Set Environment Variables

Configure Alpaca credentials for VIX fetching:

```bash
# Cloud Functions secrets
firebase functions:secrets:set APCA_API_KEY_ID
firebase functions:secrets:set APCA_API_SECRET_KEY
firebase functions:secrets:set APCA_API_BASE_URL
```

## Monitoring

### CloudWatch / Cloud Logging

Monitor circuit breaker activity:

```
# Daily Loss Limit triggers
logger.critical("🚨 DAILY LOSS LIMIT BREACHED")

# VIX Guard triggers
logger.warning("⚠️  VIX GUARD ACTIVATED")

# Concentration triggers
logger.warning("⚠️  CONCENTRATION GUARD ACTIVATED")
```

### Firestore Analytics

Query circuit breaker events:

```javascript
// Count breakers by type (last 24 hours)
db.collectionGroup('circuit_breaker_events')
  .where('timestamp', '>', yesterday)
  .get()
  .then(snapshot => {
    const counts = {};
    snapshot.forEach(doc => {
      const type = doc.data().breaker_type;
      counts[type] = (counts[type] || 0) + 1;
    });
    console.log('Circuit breaker triggers:', counts);
  });
```

## Best Practices

1. **Monitor VIX Ingestion**: Ensure VIX data is being fetched regularly
2. **Review Thresholds**: Adjust thresholds based on strategy risk profiles
3. **Test in Shadow Mode**: Test circuit breakers in shadow mode before live trading
4. **Alert on Failures**: Set up alerts for circuit breaker failures or errors
5. **Audit Events**: Regularly review circuit breaker events for patterns

## Troubleshooting

### VIX Data Not Available

**Symptom**: VIX guard not activating even when volatility is high

**Solutions**:
1. Check Cloud Function logs: `firebase functions:log --only ingest_vix_data`
2. Verify Alpaca credentials are set correctly
3. Check Firestore path: `systemStatus/vix_data`
4. Manually trigger VIX fetch for testing

### Daily Loss Limit Not Triggering

**Symptom**: Trading continues despite losses > -2%

**Solutions**:
1. Verify trades are being recorded in ledger_trades collection
2. Check starting_equity is calculated correctly
3. Review PnL calculation logic in check_daily_loss_limit()
4. Ensure timezone handling is correct (all times should be UTC)

### Concentration Check Too Aggressive

**Symptom**: Too many BUY signals being downgraded to HOLD

**Solutions**:
1. Review portfolio value calculation
2. Adjust CONCENTRATION_THRESHOLD (default: 0.20 = 20%)
3. Consider position-specific thresholds for different asset classes

## Future Enhancements

1. **Dynamic Thresholds**: Adjust thresholds based on account size or risk tolerance
2. **Multi-Timeframe Loss Limits**: Add hourly, weekly, monthly limits
3. **Drawdown Protection**: Implement max drawdown circuit breaker
4. **Volatility Regime Detection**: Use VIX trends (not just absolute level)
5. **Correlation Checks**: Prevent over-concentration in correlated positions
6. **Email/SMS Notifications**: Add additional notification channels
7. **Recovery Mode**: Automatic re-enabling after cooling-off period

## References

- Circuit Breaker Pattern: [Martin Fowler](https://martinfowler.com/bliki/CircuitBreaker.html)
- VIX Index: [CBOE VIX](https://www.cboe.com/tradable_products/vix/)
- Risk Management: [Quantopian Lectures](https://www.quantopian.com/lectures)

## Support

For questions or issues:
- Review logs in Cloud Functions console
- Check Firestore collections for event audit trail
- Run test suite: `pytest tests/test_circuit_breakers.py -v`
