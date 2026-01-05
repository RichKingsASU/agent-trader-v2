# Risk Manager - Quick Start Guide

## 🚀 5-Minute Setup

### 1. Import the Module

```python
from functions.risk_manager import (
    validate_trade_risk,
    AccountSnapshot,
    TradeRequest,
    RiskCheckResult
)
```

### 2. Set Up High Water Mark in Firestore

```python
from firebase_admin import firestore

db = firestore.client()
db.collection("riskManagement").document("highWaterMark").set({
    "value": 100000.0,  # Your account's peak equity
    "updated_at": firestore.SERVER_TIMESTAMP
})
```

### 3. Validate Trades

```python
# Create account snapshot (from Alpaca or your data source)
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

# Validate
result = validate_trade_risk(account, trade)

if result.allowed:
    # ✅ Safe to execute
    execute_trade(trade)
else:
    # ❌ Reject trade
    print(f"Trade rejected: {result.reason}")
```

## 📋 Safety Rules

| Rule | Limit | Action |
|------|-------|--------|
| **Equity Drawdown** | 10% below HWM | Reject trade if equity < (HWM × 0.90) |
| **Trade Size** | 5% of buying power | Reject trade if notional > (BP × 0.05) |

## ✅ Test Your Setup

```bash
# Run tests to verify installation
pytest tests/test_risk_manager.py -v

# Expected: 34 passed
```

## 📖 Full Documentation

- **Complete Guide**: `functions/RISK_MANAGER_README.md`
- **Implementation Summary**: `functions/RISK_MANAGER_SUMMARY.md`
- **Examples**: `functions/risk_manager_example.py`

## 🔧 Common Integration Patterns

### Pattern 1: Pre-Execution Check

```python
def execute_trade(account, trade):
    # Validate first
    result = validate_trade_risk(account, trade)
    if not result.allowed:
        return {"status": "rejected", "reason": result.reason}
    
    # Execute if validation passed
    order = submit_order(trade)
    return {"status": "success", "order": order}
```

### Pattern 2: Batch Validation

```python
def validate_multiple_trades(account, trades):
    results = []
    for trade in trades:
        result = validate_trade_risk(account, trade)
        results.append({
            "trade": trade,
            "allowed": result.allowed,
            "reason": result.reason
        })
    return results
```

### Pattern 3: Firebase Function

```python
from firebase_functions import https_fn

@https_fn.on_call()
def check_trade_risk(req: https_fn.CallableRequest):
    account = AccountSnapshot(**req.data["account"])
    trade = TradeRequest(**req.data["trade"])
    
    result = validate_trade_risk(account, trade)
    
    return {
        "allowed": result.allowed,
        "reason": result.reason
    }
```

## 🎯 Quick Examples

### Example 1: Valid Trade ✅
```python
account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
trade = TradeRequest(symbol="AAPL", side="buy", qty=100, notional_usd=2000)
# Result: ALLOWED (equity 5% below HWM, trade 4% of BP)
```

### Example 2: HWM Violation ❌
```python
account = AccountSnapshot(equity=85000, buying_power=50000, cash=25000)
trade = TradeRequest(symbol="MSFT", side="buy", qty=50, notional_usd=1000)
# Result: REJECTED (equity 15% below HWM, exceeds 10% limit)
```

### Example 3: Oversized Trade ❌
```python
account = AccountSnapshot(equity=95000, buying_power=50000, cash=25000)
trade = TradeRequest(symbol="TSLA", side="buy", qty=200, notional_usd=5000)
# Result: REJECTED (trade is 10% of BP, exceeds 5% limit)
```

## 🐛 Troubleshooting

### "High Water Mark document not found"
**Solution**: Create the HWM document in Firestore (see step 2 above)

### All trades rejected
**Check**:
1. Is HWM set correctly? (not too high)
2. Is account snapshot current?
3. Are trade sizes reasonable?

### Tests fail with Firebase credentials error
**Normal**: Tests use mocks. Only actual Firestore operations need credentials.

## 📞 Need Help?

- Read the full documentation: `RISK_MANAGER_README.md`
- Check the examples: `risk_manager_example.py`
- Review the test suite: `tests/test_risk_manager.py`

---

**Remember**: This is a safety-critical module. Always test thoroughly before production use!
