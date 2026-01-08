# Risk Management Module

Smart Risk Circuit Breakers for automated capital protection.

## Overview

This module implements three circuit breakers that automatically protect user capital during adverse market conditions:

1. **Daily Loss Limit** (-2%): Switches all strategies to SHADOW_MODE when daily PnL drops below -2%
2. **VIX Guard** (VIX > 30): Reduces position sizing by 50% during high market volatility
3. **Concentration Check** (> 20%): Prevents over-concentration in single positions

## Quick Start

### Basic Usage

```python
from backend.risk.base_strategy_wrapper import evaluate_strategy_with_circuit_breakers

signal = await evaluate_strategy_with_circuit_breakers(
    strategy=strategy_instance,
    market_data=market_data,
    account_snapshot=account_snapshot,
    user_id=user_id,
    tenant_id=tenant_id,
    strategy_id=strategy_id,
    db=firestore_client,
)
```

### Advanced Usage

```python
from backend.risk.circuit_breakers import CircuitBreakerManager
from backend.risk.notifications import NotificationService
from backend.risk.strategy_integration import StrategyCircuitBreakerWrapper

# Initialize services
notification_service = NotificationService(db_client=db)
cb_manager = CircuitBreakerManager(
    db_client=db,
    notification_service=notification_service,
)
wrapper = StrategyCircuitBreakerWrapper(
    circuit_breaker_manager=cb_manager,
    notification_service=notification_service,
)

# Evaluate with circuit breakers
signal = await wrapper.evaluate_with_circuit_breakers(
    tenant_id=tenant_id,
    user_id=user_id,
    strategy_id=strategy_id,
    signal=original_signal,
    account_snapshot=account_snapshot,
    trades_today=trades_today,
    starting_equity=starting_equity,
)
```

## Module Contents

### circuit_breakers.py

Core circuit breaker logic implementing all three risk controls.

**Classes**:
- `CircuitBreakerManager`: Main manager for all circuit breakers
- `CircuitBreakerEvent`: Event data class
- `CircuitBreakerType`: Enum of breaker types

**Key Methods**:
- `check_daily_loss_limit()`: Check if daily loss exceeds -2%
- `check_vix_guard()`: Check VIX and reduce allocation if needed
- `check_concentration()`: Check position concentration before BUY
- `handle_circuit_breaker_event()`: Log and notify
- `switch_strategies_to_shadow_mode()`: Emergency shutdown

### vix_ingestion.py

VIX (Volatility Index) data fetching and storage service.

**Classes**:
- `VIXIngestionService`: Fetches VIX from Alpaca or Yahoo Finance

**Key Methods**:
- `fetch_and_store_vix()`: Fetch current VIX and store in Firestore
- `get_cached_vix()`: Get cached VIX value
- `manual_set_vix()`: Set VIX manually (for testing)

**Scheduled Function**: `functions/scheduled_vix_ingestion.py` runs every 5 minutes

### notifications.py

User notification service for circuit breaker events.

**Classes**:
- `NotificationService`: Send notifications to users

**Key Methods**:
- `send_notification()`: Generic notification sender
- `send_daily_loss_alert()`: Daily loss limit alert
- `send_vix_guard_alert()`: VIX guard alert
- `send_concentration_alert()`: Concentration limit alert

**Storage**: Notifications stored at `users/{userId}/notifications/`

### strategy_integration.py

Integration wrapper for applying circuit breakers to strategy signals.

**Classes**:
- `StrategyCircuitBreakerWrapper`: Wraps strategy evaluation

**Key Methods**:
- `evaluate_with_circuit_breakers()`: Apply all circuit breakers to a signal

**Flow**:
1. Check daily loss limit (critical)
2. Check VIX guard (reduce allocation)
3. Check concentration (downgrade BUY to HOLD)
4. Send notifications
5. Store audit events
6. Return adjusted signal

### base_strategy_wrapper.py

Main integration point for BaseStrategy evaluation with circuit breakers.

**Functions**:
- `evaluate_strategy_with_circuit_breakers()`: Main wrapper function
- `get_starting_equity_for_day()`: Fetch starting equity
- `_fetch_trades_today()`: Get today's trades for PnL calculation

**Usage**: Replace `strategy.evaluate()` with this wrapper function.

## Configuration

### Thresholds

Default thresholds in `CircuitBreakerManager`:

```python
DAILY_LOSS_THRESHOLD = -0.02  # -2%
VIX_THRESHOLD = 30.0
CONCENTRATION_THRESHOLD = 0.20  # 20%
ALLOCATION_REDUCTION_FACTOR = 0.5  # 50% reduction
```

### VIX Ingestion

- **Frequency**: Every 5 minutes
- **Primary Source**: Alpaca
- **Fallback Source**: Yahoo Finance
- **Storage**: `systemStatus/vix_data`
- **Cache TTL**: 5 minutes

## Data Storage

### VIX Data

**Path**: `systemStatus/vix_data`

```json
{
  "current_value": 32.5,
  "updated_at": "2025-12-30T10:30:00Z",
  "source": "alpaca"
}
```

### Circuit Breaker Events

**Path**: `users/{userId}/circuit_breaker_events/{auto_id}`

```json
{
  "breaker_type": "daily_loss_limit",
  "timestamp": "2025-12-30T14:15:00Z",
  "severity": "critical",
  "message": "Daily loss limit breached...",
  "metadata": {...}
}
```

### Notifications

**Path**: `users/{userId}/notifications/{auto_id}`

```json
{
  "title": "🚨 Daily Loss Limit Breached",
  "message": "...",
  "severity": "critical",
  "created_at": "2025-12-30T14:15:00Z",
  "read": false
}
```

## Testing

Run the comprehensive test suite:

```bash
pip install pytest pytest-asyncio
pytest tests/test_circuit_breakers.py -v
```

**Test Coverage**:
- ✅ Daily loss limit scenarios
- ✅ VIX guard activation
- ✅ Concentration checks
- ✅ Event handling
- ✅ Notification sending
- ✅ Shadow mode switching

## Deployment

### 1. Deploy VIX Ingestion

```bash
cd functions
firebase deploy --only functions:ingest_vix_data
firebase deploy --only functions:initialize_daily_vix
```

### 2. Set Secrets

```bash
firebase functions:secrets:set APCA_API_KEY_ID
firebase functions:secrets:set APCA_API_SECRET_KEY
firebase functions:secrets:set APCA_API_BASE_URL
```

### 3. Update Strategy Code

Replace strategy evaluation with circuit breaker wrapper (see Quick Start above).

### 4. Monitor

- Check VIX ingestion: `systemStatus/vix_data`
- Monitor events: `users/{userId}/circuit_breaker_events`
- Review notifications: `users/{userId}/notifications`

## Monitoring

### Logs

```bash
# VIX ingestion
firebase functions:log --only ingest_vix_data

# Circuit breakers
gcloud logging read "textPayload=~'CIRCUIT BREAKER'"
```

### Metrics

- VIX ingestion success rate
- Circuit breaker trigger frequency
- Daily loss limit breaches (should be rare)
- VIX guard activations (during volatile periods)

## Error Handling

All components include comprehensive error handling:

- **VIX Unavailable**: Circuit breaker skips VIX guard
- **Database Errors**: Graceful degradation, logs errors
- **Notification Failures**: Logged but don't block execution
- **PnL Calculation Errors**: Returns safe defaults

## Performance

- **Async Operations**: All checks run asynchronously
- **Caching**: VIX data cached for 5 minutes
- **Efficient Queries**: Indexed Firestore queries
- **Error Isolation**: One breaker failure doesn't affect others

## Documentation

- **Full Implementation Guide**: `/docs/CIRCUIT_BREAKERS_IMPLEMENTATION.md`
- **Integration Examples**: `/docs/CIRCUIT_BREAKERS_INTEGRATION_EXAMPLE.md`
- **Summary**: `/docs/CIRCUIT_BREAKERS_SUMMARY.md`
- **This README**: `/backend/risk/README.md`

## Support

For questions or issues:
1. Review implementation documentation
2. Check Cloud Functions logs
3. Inspect Firestore event audit trail
4. Run test suite to verify behavior

## License

Part of the trading platform codebase.

---

**Implementation Status**: ✅ Complete and Production-Ready

All circuit breakers are fully implemented, tested, and documented.
