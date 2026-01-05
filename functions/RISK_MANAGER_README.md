# Risk Manager - Kill-Switch Documentation

## Overview

The Risk Manager provides safety "kill-switch" logic to prevent trades under dangerous market or account conditions. It implements two critical safety checks:

1. **High Water Mark (HWM) Drawdown Check**: Rejects trades if current equity falls more than 10% below the high water mark
2. **Trade Size Check**: Rejects trades if the trade size exceeds 5% of buying power

## Installation

The risk manager is located in `functions/risk_manager.py` and requires the following dependencies (already in `functions/requirements.txt`):

- `firebase-admin` - For Firestore access
- `firebase-functions` - For Firebase functions support

## Data Structures

### AccountSnapshot

Represents the current state of a trading account:

```python
from functions.risk_manager import AccountSnapshot

account = AccountSnapshot(
    equity=100000.0,      # Current account equity (total value)
    buying_power=50000.0, # Available buying power
    cash=25000.0          # Available cash
)
```

### TradeRequest

Represents a proposed trade:

```python
from functions.risk_manager import TradeRequest

trade = TradeRequest(
    symbol="AAPL",          # Trading symbol
    side="buy",             # "buy" or "sell"
    qty=100,                # Number of shares/contracts
    notional_usd=15000.0    # Total dollar value of trade
)
```

### RiskCheckResult

Result of the risk validation:

```python
from functions.risk_manager import RiskCheckResult

result = RiskCheckResult(
    allowed=True,         # True if trade is allowed, False if rejected
    reason=None          # None if allowed, error message if rejected
)
```

## Usage

### Basic Usage

```python
from functions.risk_manager import validate_trade_risk, AccountSnapshot, TradeRequest

# Create account snapshot (typically from Alpaca API or Firestore)
account = AccountSnapshot(
    equity=95000.0,
    buying_power=50000.0,
    cash=25000.0
)

# Create trade request
trade = TradeRequest(
    symbol="AAPL",
    side="buy",
    qty=100,
    notional_usd=2000.0
)

# Validate the trade
result = validate_trade_risk(account, trade)

if result.allowed:
    # Proceed with trade execution
    print("Trade validation passed - executing trade")
    # execute_trade(trade)
else:
    # Reject the trade
    print(f"Trade rejected: {result.reason}")
```

### Integration with Trade Execution

The `validate_trade_risk` function is designed to be used as a pre-execution check in your trade execution pipeline:

```python
def execute_trade(account_snapshot, trade_request):
    """
    Execute a trade with risk validation.
    """
    # Step 1: Validate trade against risk rules
    risk_check = validate_trade_risk(account_snapshot, trade_request)
    
    if not risk_check.allowed:
        logger.error(f"Trade rejected by risk manager: {risk_check.reason}")
        return {
            "status": "rejected",
            "reason": risk_check.reason
        }
    
    # Step 2: Proceed with trade execution
    # ... (your trade execution logic here)
    
    return {
        "status": "success",
        "order_id": "..."
    }
```

### Using with Firebase Functions

```python
from firebase_functions import scheduler_fn
from firebase_admin import firestore
from functions.risk_manager import validate_trade_risk, AccountSnapshot, TradeRequest

@scheduler_fn.on_schedule(schedule="*/5 * * * *")
def scheduled_trade_check(event):
    """
    Example Firebase function that validates trades on a schedule.
    """
    db = firestore.client()
    
    # Fetch account snapshot from Firestore
    account_doc = db.collection("alpacaAccounts").document("snapshot").get()
    account_data = account_doc.to_dict() or {}
    
    account = AccountSnapshot(
        equity=float(account_data.get("equity", 0)),
        buying_power=float(account_data.get("buying_power", 0)),
        cash=float(account_data.get("cash", 0))
    )
    
    # Check pending trades
    pending_trades = db.collection("pendingTrades").where("status", "==", "pending").stream()
    
    for trade_doc in pending_trades:
        trade_data = trade_doc.to_dict()
        
        trade = TradeRequest(
            symbol=trade_data["symbol"],
            side=trade_data["side"],
            qty=trade_data["qty"],
            notional_usd=trade_data["notional_usd"]
        )
        
        result = validate_trade_risk(account, trade, db=db)
        
        if not result.allowed:
            # Mark trade as rejected
            trade_doc.reference.update({
                "status": "rejected",
                "rejection_reason": result.reason
            })
```

## Firestore Setup

### High Water Mark Configuration

The High Water Mark must be stored in Firestore at the following location:

**Collection**: `riskManagement`
**Document**: `highWaterMark`

**Document Schema**:
```json
{
  "value": 100000.0,
  "updated_at": "2025-12-30T10:00:00Z",
  "updated_by": "system"
}
```

### Setting the High Water Mark

You can set the high water mark using the Firebase console or programmatically:

```python
from firebase_admin import firestore
from datetime import datetime, timezone

db = firestore.client()

# Set high water mark
db.collection("riskManagement").document("highWaterMark").set({
    "value": 100000.0,
    "updated_at": datetime.now(timezone.utc).isoformat(),
    "updated_by": "admin"
})
```

### Updating High Water Mark

The high water mark should be updated periodically when the account reaches new equity highs:

```python
def update_high_water_mark_if_needed(current_equity):
    """
    Update HWM if current equity exceeds it.
    """
    db = firestore.client()
    hwm_ref = db.collection("riskManagement").document("highWaterMark")
    
    hwm_doc = hwm_ref.get()
    if not hwm_doc.exists:
        # First time - set HWM
        hwm_ref.set({
            "value": current_equity,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": "system"
        })
        return
    
    current_hwm = hwm_doc.to_dict().get("value", 0)
    
    if current_equity > current_hwm:
        # New high - update HWM
        hwm_ref.update({
            "value": current_equity,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": "system"
        })
```

## Safety Rules

### Rule 1: High Water Mark Drawdown (10% limit)

**Purpose**: Prevent trading when account equity has dropped significantly from its peak.

**Logic**:
- Retrieves HWM from Firestore (`riskManagement/highWaterMark`)
- Calculates threshold: `HWM * 0.90` (90% of HWM)
- Rejects trade if: `current_equity < threshold`

**Example**:
- HWM: $100,000
- Threshold: $90,000 (10% drawdown)
- Current Equity: $85,000
- **Result**: ❌ Trade rejected (15% drawdown exceeds 10% limit)

**Example (Pass)**:
- HWM: $100,000
- Threshold: $90,000
- Current Equity: $95,000
- **Result**: ✅ Trade allowed (5% drawdown within 10% limit)

### Rule 2: Trade Size (5% of buying power limit)

**Purpose**: Prevent oversized trades that could risk too much capital.

**Logic**:
- Calculates max allowed: `buying_power * 0.05` (5% of buying power)
- Rejects trade if: `trade_notional > max_allowed`

**Example**:
- Buying Power: $50,000
- Max Allowed: $2,500 (5% of buying power)
- Trade Size: $5,000
- **Result**: ❌ Trade rejected (10% of buying power exceeds 5% limit)

**Example (Pass)**:
- Buying Power: $50,000
- Max Allowed: $2,500
- Trade Size: $2,000
- **Result**: ✅ Trade allowed (4% of buying power within 5% limit)

## Error Handling

The risk manager handles various error conditions gracefully:

### Missing High Water Mark

If the HWM is not set in Firestore:
- Logs a warning
- **Passes the HWM check** (only validates trade size)
- Recommendation: Set HWM before using in production

### Invalid Account Data

If account snapshot has negative values:
- Rejects trade immediately
- Returns error: "Invalid account snapshot: equity is negative"

### Firestore Connection Issues

If Firestore is unavailable:
- Logs the exception
- Returns `None` for HWM
- Passes HWM check with warning
- Still validates trade size

## Logging

The risk manager provides detailed logging:

```python
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("functions.risk_manager")

# Risk manager will log:
# - INFO: Successful trade validations
# - WARNING: Missing HWM, stale data, edge cases
# - ERROR: Trade rejections with details
```

**Example Log Messages**:

✅ **Trade Approved**:
```
INFO: Trade validation passed: BUY AAPL 100 shares, notional=$15000.00 (3.00% of buying power)
```

❌ **Trade Rejected (HWM)**:
```
ERROR: Trade rejected: KILL-SWITCH: Current equity $85,000.00 is 15.00% below High Water Mark $100,000.00 (threshold: $90,000.00, max allowed drawdown: 10%)
```

❌ **Trade Rejected (Size)**:
```
ERROR: Trade rejected: KILL-SWITCH: Trade size $5,000.00 (10.00% of buying power) exceeds maximum allowed $2,500.00 (5% of buying power $50,000.00)
```

## Testing

Comprehensive tests are provided in `tests/test_risk_manager.py`:

```bash
# Run all tests
pytest tests/test_risk_manager.py -v

# Run specific test class
pytest tests/test_risk_manager.py::TestValidateTradeRisk -v

# Run with coverage
pytest tests/test_risk_manager.py --cov=functions.risk_manager
```

**Test Coverage**:
- Helper functions (type conversion, validation)
- HWM drawdown checks (various scenarios)
- Trade size checks (various scenarios)
- Integration tests (combined validation)
- Edge cases (boundary conditions, error handling)
- Data class creation

## Best Practices

### 1. Always Validate Before Execution

```python
# ✅ GOOD: Validate before executing
result = validate_trade_risk(account, trade)
if result.allowed:
    execute_trade(trade)

# ❌ BAD: Execute without validation
execute_trade(trade)  # No safety check!
```

### 2. Update High Water Mark Regularly

```python
# Update HWM daily or when equity increases
if current_equity > stored_hwm:
    update_high_water_mark(current_equity)
```

### 3. Log All Rejections

```python
result = validate_trade_risk(account, trade)
if not result.allowed:
    logger.error(f"Trade rejected for {trade.symbol}: {result.reason}")
    # Optionally: store rejection in Firestore for audit trail
```

### 4. Monitor Rejection Rates

Track how often trades are rejected to identify:
- Account health issues (frequent HWM violations)
- Strategy issues (oversized positions)
- Configuration issues (HWM set incorrectly)

### 5. Test with Production-like Data

```python
# Test with realistic account values
test_cases = [
    (95000, 2000, True),   # Should pass
    (85000, 2000, False),  # Should fail (HWM)
    (95000, 5000, False),  # Should fail (size)
]

for equity, notional, expected in test_cases:
    account = AccountSnapshot(equity=equity, buying_power=50000, cash=25000)
    trade = TradeRequest(symbol="TEST", side="buy", qty=1, notional_usd=notional)
    result = validate_trade_risk(account, trade)
    assert result.allowed == expected
```

## Customization

To adjust the safety thresholds, modify the constants in `risk_manager.py`:

```python
# Current thresholds
HWM_THRESHOLD = 0.90  # 10% drawdown limit (90% of HWM)
SIZE_THRESHOLD = 0.05  # 5% of buying power

# Example: More conservative (5% drawdown, 2% size limit)
HWM_THRESHOLD = 0.95
SIZE_THRESHOLD = 0.02

# Example: More aggressive (15% drawdown, 10% size limit)
HWM_THRESHOLD = 0.85
SIZE_THRESHOLD = 0.10
```

**Note**: Modifying thresholds requires updating the corresponding logic in `_check_high_water_mark()` and `_check_trade_size()`.

## Support and Troubleshooting

### Common Issues

**Issue**: "High Water Mark document not found"
**Solution**: Create HWM document in Firestore at `riskManagement/highWaterMark`

**Issue**: "Buying power is $0.00"
**Solution**: Ensure account snapshot is current and accurate

**Issue**: All trades rejected
**Solution**: 
1. Check if HWM is set too high
2. Verify account snapshot is recent
3. Review trade size calculations

### Debug Mode

Enable debug logging for detailed information:

```python
import logging
logging.getLogger("functions.risk_manager").setLevel(logging.DEBUG)
```

## Future Enhancements

Potential improvements for future versions:

1. **Time-based Rules**: Restrict trading during specific hours
2. **Volatility Checks**: Adjust limits based on market volatility
3. **Symbol-specific Rules**: Different limits per symbol/asset class
4. **Daily Loss Limits**: Stop trading after reaching daily loss threshold
5. **Position Concentration**: Limit exposure to any single symbol
6. **Correlation Limits**: Prevent over-concentration in correlated assets

## License

This code is part of the AgentTrader project.
