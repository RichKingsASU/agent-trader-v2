# Risk Management Kill-Switch System

## Overview

This document describes the production-grade Risk Management system implemented for AgentTrader, featuring:

- **High Water Mark (HWM) Tracking**: Monitors the highest account equity ever achieved
- **Drawdown Monitoring**: Calculates real-time drawdown from HWM
- **Automatic Kill-Switch**: Disables trading if drawdown exceeds 5% threshold
- **Emergency Liquidation**: Manual panic button to close all positions and cancel all orders
- **Signal Generation Safety Layer**: Blocks AI-generated signals when trading is disabled

## Architecture

### Backend Components

#### 1. Risk Manager (`functions/risk_manager.py`)

Core risk calculation module with the following functions:

##### `update_risk_state(db, current_equity_str, drawdown_threshold=None)`

Updates risk management state every minute (called by `pulse` function):

- **Reads** current `high_water_mark` from Firestore
- **Updates** HWM if current equity is higher (new peak)
- **Calculates** drawdown: `(HWM - Current) / HWM`
- **Sets** `trading_enabled` flag based on drawdown threshold (default: 5%)

**Firestore Schema:**
```
systemStatus/risk_management:
  high_water_mark: string           # Stored as string for Decimal precision
  current_equity: string             # Current account equity
  drawdown_percent: number           # Current drawdown (0.05 = 5%)
  trading_enabled: boolean           # Master kill-switch flag
  last_updated: timestamp            # Last update time
  last_hwm_update: timestamp         # When HWM was last increased
  drawdown_breached_at: timestamp    # When kill-switch was triggered
```

##### `calculate_drawdown(current_equity, high_water_mark)`

Pure calculation function:
- Returns `(drawdown_percentage, is_breached)`
- Uses `Decimal` for financial precision
- Formula: `(HWM - Current) / HWM`

##### `get_trading_enabled(db)`

Fast read-only check for signal generators:
- Returns `(trading_enabled, reason)`
- Conservative: disables trading on any error
- Used by AI signal generation to block trades during drawdown

##### `manual_override_trading(db, enabled, override_reason)`

Allows operators to manually override the kill-switch:
- Used for maintenance, recovery, or emergency situations
- Logs override reason for audit trail

#### 2. Enhanced Pulse Function (`functions/main.py`)

The scheduled `pulse` function (runs every minute) now:

1. **Syncs Alpaca account** to Firestore (`alpacaAccounts/snapshot`)
2. **Updates risk state** via `update_risk_state()`
3. **Logs risk metrics** (HWM, drawdown, trading status)

**Key Features:**
- Non-blocking: Risk management errors don't fail account sync
- Financial precision: Uses string-based Decimal conversion
- Audit logging: All state changes logged with timestamps

#### 3. Emergency Liquidation (`functions/main.py::emergency_liquidate`)

Firebase Callable Function for panic button:

**Input:**
```json
{
  "confirmation": "LIQUIDATE_ALL"
}
```

**Actions:**
1. Cancel all open orders via `api.cancel_all_orders()`
2. Close all positions via `api.close_all_positions(cancel_orders=True)`
3. Set system status to `EMERGENCY_HALT`
4. Disable trading in risk management state
5. Log who triggered the liquidation

**Output:**
```json
{
  "success": true,
  "orders_cancelled": 5,
  "positions_closed": 3,
  "message": "Emergency liquidation completed..."
}
```

**Security:**
- Requires explicit `LIQUIDATE_ALL` confirmation
- Logs user ID who triggered it
- Returns detailed results for audit

#### 4. Signal Generation Safety Layer (`backend/alpaca_signal_trader.py`)

Modified `generate_signal_with_warm_cache()` to include two safety layers:

**SAFETY LAYER 1: Trading Enabled Check**
```python
# Check risk management kill-switch
risk_doc = db.collection("systemStatus").document("risk_management").get()
if not risk_doc.get("trading_enabled"):
    return TradeSignal(action="flat", reason="System in Drawdown Recovery Mode")
```

**SAFETY LAYER 2: Affordability Check** (existing)
```python
# Check buying power
if buying_power_usd <= 0:
    return TradeSignal(action="flat", reason="Insufficient buying power")
```

**Benefits:**
- AI never generates signals during drawdown
- Fast pre-flight check (no Alpaca API call needed)
- Conservative: blocks on any error

### Frontend Components

#### 1. PanicButton Component (`frontend/src/components/PanicButton.tsx`)

High-visibility emergency liquidation button with double-confirmation:

**Features:**
- Two variants: `default` (large with glow) and `compact`
- **Double-confirmation**: Two separate dialogs to prevent accidents
- Shows detailed list of actions that will be taken
- Calls Firebase `emergency_liquidate` function
- Toast notifications for success/failure

**First Confirmation Dialog:**
- Basic warning about closing all positions
- "Are you absolutely sure?" message

**Second Confirmation Dialog:**
- Red border and pulsing icon
- Detailed list of actions
- "FINAL CONFIRMATION" title
- "This cannot be undone" warning

#### 2. Integration Points

**MasterControlPanel** (`frontend/src/components/MasterControlPanel.tsx`):
- Replaced old panic button with new `PanicButton` component
- Positioned at bottom of control panel with red border separator

**DashboardHeader** (`frontend/src/components/DashboardHeader.tsx`):
- Added compact panic button to header (always visible)
- Positioned next to layout controls for quick access

#### 3. Firebase Functions Setup (`frontend/src/firebase.ts`)

Added Functions SDK initialization:
```typescript
import { getFunctions } from "firebase/functions";
const functions = getFunctions(app);
export { db, auth, app, functions };
```

## Configuration

### Drawdown Threshold

Default: **5%** (configurable in `functions/risk_manager.py`)

```python
DEFAULT_DRAWDOWN_THRESHOLD = Decimal("0.05")  # 5%
```

**Future Enhancement:** Make this user-configurable via Firestore:
```
tenants/{tenant_id}/settings/risk_management:
  drawdown_threshold: 0.05  # 5%
  min_equity_tracking: 100.0
```

### Minimum Equity for Tracking

Default: **$100** (prevents tracking test accounts)

```python
MIN_EQUITY_FOR_TRACKING = Decimal("100.0")
```

## Deployment

### Functions Deployment

1. Deploy Firebase Functions:
```bash
cd functions
firebase deploy --only functions:pulse,functions:emergency_liquidate
```

2. Ensure Secret Manager secrets are configured:
```bash
# Required secrets (already set up):
- ALPACA_KEY_ID
- ALPACA_SECRET_KEY
```

### Frontend Deployment

1. Build frontend with updated components:
```bash
cd frontend
npm run build
```

2. Deploy to Firebase Hosting:
```bash
firebase deploy --only hosting
```

## Monitoring & Alerts

### Key Metrics to Monitor

1. **High Water Mark Progression**
   - Query: `systemStatus/risk_management.high_water_mark`
   - Should generally trend upward over time

2. **Drawdown Events**
   - Query: `systemStatus/risk_management.drawdown_breached_at`
   - Alert if non-null (kill-switch triggered)

3. **Emergency Liquidations**
   - Query: `systemStatus/trading.emergency_liquidation_at`
   - Alert immediately (manual intervention)

### Recommended Alerts

1. **Kill-Switch Triggered**
```
Alert: Trading disabled due to 5% drawdown
Query: systemStatus/risk_management.trading_enabled == false
Action: Investigate market conditions, review strategy
```

2. **Emergency Liquidation**
```
Alert: Manual emergency liquidation executed
Query: systemStatus/trading.status == "EMERGENCY_HALT"
Action: Review logs, contact operator, assess damage
```

## Recovery Procedures

### After Kill-Switch Triggers

1. **Investigate Root Cause**
   - Review recent trades and signals
   - Check market conditions (volatility, news events)
   - Analyze strategy performance

2. **Wait for Recovery**
   - System will auto-re-enable when equity recovers
   - Drawdown must fall below threshold
   - Or manually override if needed

3. **Manual Override (if needed)**
```python
from functions.risk_manager import manual_override_trading
manual_override_trading(
    db=db,
    enabled=True,
    override_reason="Manual recovery after market analysis"
)
```

### After Emergency Liquidation

1. **Verify All Positions Closed**
   - Check Alpaca dashboard
   - Verify Firestore position records

2. **Update System Status**
```python
# Reset trading status
db.collection("systemStatus").document("trading").set({
    "status": "OPERATIONAL",
    "resumed_at": firestore.SERVER_TIMESTAMP,
})
```

3. **Re-enable Trading**
```python
manual_override_trading(
    db=db,
    enabled=True,
    override_reason="System verified, resuming operations"
)
```

## Testing

### Unit Tests

Test the risk calculation logic:

```python
# tests/test_risk_manager.py
from decimal import Decimal
from functions.risk_manager import calculate_drawdown

def test_drawdown_calculation():
    hwm = Decimal("10000")
    current = Decimal("9500")
    drawdown, breached = calculate_drawdown(current, hwm)
    assert drawdown == Decimal("0.05")  # 5%
    assert breached == False  # At threshold, not breached
    
    current = Decimal("9400")
    drawdown, breached = calculate_drawdown(current, hwm)
    assert drawdown == Decimal("0.06")  # 6%
    assert breached == True  # Exceeds 5% threshold
```

### Integration Tests

Test the full flow:

```python
# tests/test_risk_integration.py
def test_pulse_updates_hwm(firestore_client):
    # Simulate pulse with high equity
    payload = {"equity": "10000"}
    # ... pulse logic ...
    
    risk_doc = firestore_client.collection("systemStatus").document("risk_management").get()
    assert risk_doc.get("high_water_mark") == "10000"
    assert risk_doc.get("trading_enabled") == True

def test_drawdown_disables_trading(firestore_client):
    # Set HWM
    firestore_client.collection("systemStatus").document("risk_management").set({
        "high_water_mark": "10000"
    })
    
    # Simulate pulse with 6% drawdown
    payload = {"equity": "9400"}
    # ... pulse logic ...
    
    risk_doc = firestore_client.collection("systemStatus").document("risk_management").get()
    assert risk_doc.get("trading_enabled") == False
    assert risk_doc.get("drawdown_percent") > 0.05
```

### Manual Testing (Staging Environment)

1. **Test Kill-Switch**:
```bash
# Manually set HWM high, then simulate low equity
firebase firestore set systemStatus/risk_management --data '{"high_water_mark": "10000"}'
# Run pulse with equity = 9400 (6% drawdown)
# Verify trading_enabled becomes false
```

2. **Test Panic Button**:
```bash
# Open frontend in staging
# Click Panic Button
# Verify double-confirmation flow
# Verify all positions closed
```

## Security Considerations

### Authentication

- Emergency liquidation requires Firebase Authentication
- User ID logged for audit trail
- Restrict to authorized users via Security Rules

### Firestore Security Rules

```javascript
// systemStatus collection (risk management)
match /systemStatus/{document=**} {
  // Only Cloud Functions can write
  allow read: if request.auth != null;
  allow write: if false;
}
```

### Rate Limiting

The panic button has built-in protection:
- Disabled state during liquidation
- No retry on failure (requires manual review)

## Future Enhancements

### 1. User-Configurable Thresholds

Allow users to set their own risk tolerance:
```
tenants/{tenant_id}/settings/risk_management:
  drawdown_threshold: 0.02  # 2% for conservative
  drawdown_threshold: 0.05  # 5% for moderate
  drawdown_threshold: 0.10  # 10% for aggressive
```

### 2. Position-Level Kill-Switches

Per-position risk limits:
- Max loss per trade: -2% of account
- Max position size: 20% of account

### 3. Daily Loss Limits

Hard daily loss limits:
- Stop trading if daily loss exceeds -3%
- Reset at market open

### 4. Volatility-Adjusted Thresholds

Dynamic risk limits based on market conditions:
- Tighter limits during high volatility (VIX > 30)
- Looser limits during calm markets (VIX < 15)

### 5. Recovery Automation

Automated gradual re-entry:
- Reduce position sizes by 50% after recovery
- Gradually increase over 5 trading days

## Appendix: Drawdown Examples

| Scenario | HWM | Current Equity | Drawdown | Action |
|----------|-----|----------------|----------|--------|
| New Peak | $10,000 | $10,500 | 0% | Update HWM ✅ |
| Small Loss | $10,500 | $10,200 | 2.86% | Continue Trading ✅ |
| Threshold | $10,500 | $9,975 | 5% | Continue (at edge) ⚠️ |
| Breach | $10,500 | $9,900 | 5.71% | **KILL-SWITCH** 🚨 |
| Recovery | $10,500 | $10,000 | 4.76% | Re-enable Trading ✅ |
| New Peak | $10,500 | $11,000 | 0% | Update HWM to $11,000 ✅ |

## Contact

For questions or issues with the Risk Management system:
- Review logs in Firebase Console
- Check systemStatus/risk_management document in Firestore
- Contact DevOps team for manual overrides

---

**Last Updated:** December 30, 2025  
**Version:** 1.0.0  
**Status:** Production Ready ✅
