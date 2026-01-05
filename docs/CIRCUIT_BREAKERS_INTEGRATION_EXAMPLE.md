# Circuit Breakers Integration Example

This document shows how to integrate the Smart Risk Circuit Breakers into your existing strategy execution flow.

## Complete Integration Example

Here's how to modify your `functions/main.py` to include circuit breakers:

```python
"""
Modified main.py with Circuit Breaker Integration
"""

import logging
from typing import Any, Dict, Optional

import firebase_admin
from firebase_admin import firestore
from firebase_functions import scheduler_fn

# Import circuit breaker components
from backend.risk.base_strategy_wrapper import (
    evaluate_strategy_with_circuit_breakers,
    get_starting_equity_for_day,
)
from strategies import StrategyLoader

logger = logging.getLogger(__name__)


@scheduler_fn.on_schedule(
    schedule="*/5 * * * *",  # Every 5 minutes
    timezone="America/New_York",
)
def run_strategies_with_circuit_breakers(event: scheduler_fn.ScheduledEvent) -> None:
    """
    Run all active strategies with circuit breaker protection.
    
    This function:
    1. Iterates through all active users and strategies
    2. Fetches market data and account snapshots
    3. Evaluates each strategy with circuit breaker protection
    4. Logs all circuit breaker events
    """
    _ = event  # unused
    
    logger.info("Starting strategy evaluation with circuit breakers...")
    
    try:
        db = _get_firestore()
        
        # Get all active tenants
        tenants = db.collection("tenants").stream()
        
        for tenant_doc in tenants:
            tenant_id = tenant_doc.id
            logger.info(f"Processing tenant: {tenant_id}")
            
            # Get all users for this tenant
            users_ref = (
                db.collection("tenants")
                .document(tenant_id)
                .collection("users")
            )
            
            users = users_ref.where("status", "==", "active").stream()
            
            for user_doc in users:
                user_id = user_doc.id
                
                # Check if trading is enabled for this user
                if not _is_user_trading_enabled(db, user_id):
                    logger.info(f"Trading disabled for user {user_id}, skipping")
                    continue
                
                # Get user's strategies
                strategies_ref = users_ref.document(user_id).collection("strategies")
                active_strategies = strategies_ref.where("status", "==", "active").stream()
                
                for strategy_doc in active_strategies:
                    strategy_id = strategy_doc.id
                    strategy_data = strategy_doc.to_dict()
                    
                    # Skip if in shadow mode (unless explicitly testing)
                    execution_mode = strategy_data.get("execution_mode", "LIVE")
                    if execution_mode == "SHADOW_MODE":
                        logger.info(f"Strategy {strategy_id} is in SHADOW_MODE, skipping")
                        continue
                    
                    try:
                        await _evaluate_strategy_for_user(
                            db=db,
                            tenant_id=tenant_id,
                            user_id=user_id,
                            strategy_id=strategy_id,
                            strategy_data=strategy_data,
                        )
                    except Exception as e:
                        logger.error(
                            f"Error evaluating strategy {strategy_id} for user {user_id}: {e}",
                            exc_info=True,
                        )
                        continue
        
        logger.info("✅ Strategy evaluation completed")
        
    except Exception as e:
        logger.error(f"Error in strategy evaluation: {e}", exc_info=True)


async def _evaluate_strategy_for_user(
    *,
    db: firestore.Client,
    tenant_id: str,
    user_id: str,
    strategy_id: str,
    strategy_data: Dict[str, Any],
) -> None:
    """
    Evaluate a single strategy for a user with circuit breaker protection.
    
    Args:
        db: Firestore client
        tenant_id: Tenant ID
        user_id: User ID
        strategy_id: Strategy ID
        strategy_data: Strategy configuration
    """
    logger.info(f"Evaluating strategy {strategy_id} for user {user_id}")
    
    # 1. Get account snapshot
    account_snapshot = _get_account_snapshot(db, user_id)
    if not account_snapshot:
        logger.warning(f"No account snapshot for user {user_id}")
        return
    
    # 2. Get market data
    market_data = _get_market_data(db, strategy_data)
    if not market_data:
        logger.warning(f"No market data available")
        return
    
    # 3. Get starting equity for the day
    starting_equity = await get_starting_equity_for_day(
        db=db,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    
    if starting_equity is None:
        # Fallback to current equity
        equity_str = account_snapshot.get("equity", "0")
        try:
            starting_equity = float(equity_str)
        except (ValueError, TypeError):
            logger.error(f"Could not determine starting equity for user {user_id}")
            return
    
    # 4. Load strategy instance
    strategy_loader = StrategyLoader()
    strategy_instance = strategy_loader.get_strategy(strategy_data.get("class_name"))
    
    if not strategy_instance:
        logger.error(f"Could not load strategy: {strategy_data.get('class_name')}")
        return
    
    # 5. Evaluate strategy WITH CIRCUIT BREAKER PROTECTION
    signal = await evaluate_strategy_with_circuit_breakers(
        strategy=strategy_instance,
        market_data=market_data,
        account_snapshot=account_snapshot,
        regime=market_data.get("regime"),
        user_id=user_id,
        tenant_id=tenant_id,
        strategy_id=strategy_id,
        db=db,
        starting_equity=starting_equity,
    )
    
    # 6. Log circuit breaker activity
    if signal.get("circuit_breaker_triggered"):
        logger.warning(
            f"⚠️  Circuit breaker triggered for {strategy_id}:\n"
            f"  Messages: {signal.get('circuit_breaker_messages')}"
        )
    
    # 7. Store signal in Firestore
    _store_signal(db, tenant_id, user_id, strategy_id, signal)
    
    # 8. Execute trade if applicable (respecting circuit breaker adjustments)
    if signal.get("action") in ["BUY", "SELL"]:
        await _execute_trade(db, user_id, strategy_id, signal)
    
    logger.info(
        f"Strategy {strategy_id} evaluated: action={signal.get('action')}, "
        f"confidence={signal.get('confidence'):.2f}"
    )


def _get_account_snapshot(db: firestore.Client, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch user's account snapshot from Firestore."""
    try:
        snapshot_ref = (
            db.collection("users")
            .document(user_id)
            .collection("alpacaAccounts")
            .document("snapshot")
        )
        
        doc = snapshot_ref.get()
        if not doc.exists:
            return None
        
        return doc.to_dict()
    except Exception as e:
        logger.error(f"Error fetching account snapshot: {e}")
        return None


def _get_market_data(
    db: firestore.Client,
    strategy_data: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Fetch market data from Firestore."""
    try:
        # Get the symbol(s) this strategy trades
        symbols = strategy_data.get("symbols", [])
        if not symbols:
            return None
        
        # Fetch latest market data for primary symbol
        symbol = symbols[0]
        
        market_data_ref = (
            db.collection("marketData")
            .document("latest")
            .collection("quotes")
            .document(symbol)
        )
        
        doc = market_data_ref.get()
        if not doc.exists:
            return None
        
        data = doc.to_dict()
        
        # Add market regime if available
        regime_ref = db.collection("systemStatus").document("market_regime")
        regime_doc = regime_ref.get()
        if regime_doc.exists:
            regime_data = regime_doc.to_dict()
            data["regime"] = regime_data.get("regime")
        
        return data
    except Exception as e:
        logger.error(f"Error fetching market data: {e}")
        return None


def _store_signal(
    db: firestore.Client,
    tenant_id: str,
    user_id: str,
    strategy_id: str,
    signal: Dict[str, Any],
) -> None:
    """Store trading signal in Firestore."""
    try:
        signal_ref = (
            db.collection("tenants")
            .document(tenant_id)
            .collection("users")
            .document(user_id)
            .collection("strategies")
            .document(strategy_id)
            .collection("signals")
        )
        
        signal_ref.add({
            **signal,
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        
        logger.info(f"Stored signal for {strategy_id}")
    except Exception as e:
        logger.error(f"Error storing signal: {e}")


async def _execute_trade(
    db: firestore.Client,
    user_id: str,
    strategy_id: str,
    signal: Dict[str, Any],
) -> None:
    """
    Execute trade based on signal.
    
    Note: This respects circuit breaker adjustments:
    - Reduced allocation from VIX guard
    - Downgraded actions from concentration check
    - Blocked trades from daily loss limit
    """
    try:
        action = signal.get("action")
        allocation = signal.get("allocation", 0)
        ticker = signal.get("ticker", signal.get("symbol"))
        
        logger.info(
            f"Executing trade: {action} {ticker}, allocation=${allocation:.2f}"
        )
        
        # Your trade execution logic here
        # ...
        
    except Exception as e:
        logger.error(f"Error executing trade: {e}", exc_info=True)


def _is_user_trading_enabled(db: firestore.Client, user_id: str) -> bool:
    """Check if trading is enabled for user."""
    try:
        status_ref = (
            db.collection("users")
            .document(user_id)
            .collection("status")
            .document("trading")
        )
        
        doc = status_ref.get()
        if not doc.exists:
            return True  # Default to enabled
        
        status = doc.to_dict() or {}
        return status.get("enabled", True)
    except Exception as e:
        logger.error(f"Error checking trading status: {e}")
        return False  # Fail-safe


def _get_firestore() -> firestore.Client:
    """Get or initialize Firestore client."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    return firestore.client()
```

## Key Points

### 1. Circuit Breaker Wrapper

The main change is replacing:
```python
signal = strategy.evaluate(market_data, account_snapshot)
```

With:
```python
signal = await evaluate_strategy_with_circuit_breakers(
    strategy=strategy_instance,
    market_data=market_data,
    account_snapshot=account_snapshot,
    user_id=user_id,
    tenant_id=tenant_id,
    strategy_id=strategy_id,
    db=db,
    starting_equity=starting_equity,
)
```

### 2. Starting Equity

The circuit breaker needs to know the starting equity to calculate daily PnL percentage:

```python
starting_equity = await get_starting_equity_for_day(
    db=db,
    tenant_id=tenant_id,
    user_id=user_id,
)
```

### 3. Circuit Breaker Signals

The returned signal includes metadata about circuit breaker activity:

```python
{
    "action": "HOLD",  # May be adjusted from original BUY
    "confidence": 0.8,
    "reasoning": "[CIRCUIT BREAKER] Concentration limit exceeded...",
    "allocation": 500.0,  # May be reduced by VIX guard
    "original_allocation": 1000.0,  # Original before VIX reduction
    "circuit_breaker_triggered": True,
    "circuit_breaker_messages": [
        "VIX elevated at 35.0 (threshold: 30.0). Reducing allocation..."
    ]
}
```

### 4. Respecting Adjustments

Your trade execution should respect the circuit breaker adjustments:

```python
# Use the adjusted allocation (not original)
allocation = signal.get("allocation", 0)

# Check if action was adjusted
if signal.get("circuit_breaker_triggered"):
    logger.info(f"Circuit breaker adjustments applied: {signal.get('circuit_breaker_messages')}")
```

## Testing in Shadow Mode

Before going live, test circuit breakers in shadow mode:

1. Set a strategy to SHADOW_MODE in Firestore
2. Manually trigger circuit breakers (adjust VIX, create losing trades)
3. Verify events are logged correctly
4. Check notifications are sent
5. Confirm signals are adjusted as expected

## Monitoring

Add monitoring for circuit breaker activity:

```python
# In Cloud Functions logs
if signal.get("circuit_breaker_triggered"):
    logger.warning(
        f"Circuit breaker triggered",
        extra={
            "user_id": user_id,
            "strategy_id": strategy_id,
            "breakers": signal.get("circuit_breaker_messages"),
            "original_action": signal.get("original_action"),
            "adjusted_action": signal.get("action"),
        }
    )
```

## Alerting

Set up alerts for critical circuit breaker events:

```python
# Alert on daily loss limit
if "Daily loss limit breached" in str(signal.get("circuit_breaker_messages")):
    # Send alert to ops team
    send_ops_alert(
        severity="critical",
        message=f"Daily loss limit breached for user {user_id}",
    )
```

## Next Steps

1. Deploy the circuit breaker code to your Cloud Functions
2. Deploy the VIX ingestion function
3. Test in shadow mode
4. Monitor circuit breaker events
5. Adjust thresholds based on real-world data
6. Enable for live trading

For more details, see `CIRCUIT_BREAKERS_IMPLEMENTATION.md`.
