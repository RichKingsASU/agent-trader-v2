# Risk Management Kill-Switch - Quick Start Guide

## 🚀 Quick Start

### What Was Implemented

✅ **High Water Mark (HWM) Tracking** - Automatically tracks highest equity ever seen  
✅ **Drawdown Monitoring** - Real-time calculation of equity decline from HWM  
✅ **Auto Kill-Switch** - Trading disabled if drawdown > 5%  
✅ **Emergency Liquidation** - Panic button to close all positions  
✅ **Signal Safety Layer** - AI won't generate signals during drawdown  

### File Changes

**Backend:**
- ✨ `functions/risk_manager.py` - NEW: Core risk calculation module
- 🔧 `functions/main.py` - MODIFIED: Added HWM tracking to `pulse` + `emergency_liquidate` function
- 🔧 `backend/alpaca_signal_trader.py` - MODIFIED: Added `trading_enabled` check to signal generation
- 🔧 `functions/requirements.txt` - MODIFIED: Added google-cloud-firestore

**Frontend:**
- ✨ `frontend/src/components/PanicButton.tsx` - NEW: Emergency liquidation button with double-confirmation
- 🔧 `frontend/src/components/MasterControlPanel.tsx` - MODIFIED: Integrated PanicButton
- 🔧 `frontend/src/components/DashboardHeader.tsx` - MODIFIED: Added compact panic button to header
- 🔧 `frontend/src/firebase.ts` - MODIFIED: Added Firebase Functions SDK

**Documentation:**
- ✨ `docs/RISK_MANAGEMENT_KILLSWITCH.md` - NEW: Complete system documentation
- ✨ `docs/RISK_MANAGEMENT_QUICK_START.md` - NEW: This file

## 🎯 How It Works

### Every Minute (Automatic)

```
1. pulse function runs (Firebase Scheduler)
2. Fetches Alpaca account → equity = $9,500
3. Reads HWM from Firestore → hwm = $10,000
4. Calculates drawdown → (10,000 - 9,500) / 10,000 = 5%
5. Checks threshold → 5% ≤ 5% → trading_enabled = true ✅
6. Writes to systemStatus/risk_management
```

### When Drawdown Exceeds 5%

```
1. equity = $9,400, hwm = $10,000
2. drawdown = 6% > 5% threshold 🚨
3. trading_enabled = false
4. drawdown_breached_at = timestamp
5. Log: "🚨 KILL-SWITCH TRIGGERED!"
```

### Signal Generation (Before AI Call)

```python
# Check kill-switch BEFORE calling Gemini
risk_doc = db.collection("systemStatus").document("risk_management").get()
if not risk_doc.get("trading_enabled"):
    return TradeSignal(
        action="flat",
        reason="System in Drawdown Recovery Mode: 6% drawdown"
    )
# Otherwise, proceed with AI signal generation
```

### Manual Panic Button

```
1. User clicks "PANIC: CLOSE ALL"
2. First confirmation: "Are you sure?"
3. Second confirmation: "FINAL CONFIRMATION - This cannot be undone"
4. Calls firebase function: emergency_liquidate({ confirmation: "LIQUIDATE_ALL" })
5. Backend:
   - Cancels all orders
   - Closes all positions
   - Sets status = "EMERGENCY_HALT"
   - Disables trading
6. UI shows toast: "Cancelled 5 orders, closed 3 positions"
```

## 📊 Firestore Schema

### systemStatus/risk_management

```javascript
{
  high_water_mark: "10000.00",        // Highest equity ever (string for precision)
  current_equity: "9400.00",          // Current equity
  drawdown_percent: 0.06,             // 6% drawdown
  trading_enabled: false,             // Kill-switch state
  last_updated: Timestamp,            // Last pulse update
  last_hwm_update: Timestamp,         // When HWM was last increased
  drawdown_breached_at: Timestamp,    // When kill-switch triggered
  
  // Manual override fields (optional)
  manual_override: true,
  manual_override_reason: "Manual recovery",
  manual_override_at: Timestamp
}
```

### systemStatus/trading

```javascript
{
  status: "EMERGENCY_HALT",           // System status
  emergency_liquidation_at: Timestamp,
  initiated_by: "user_uid_123",       // Who triggered it
  orders_cancelled: 5,
  positions_closed: 3
}
```

## 🎛️ User Interface

### Master Control Panel

Located in main dashboard control panel:

```
┌─────────────────────────────────┐
│  Bot Enabled          [  ON  ]  │
│  Buying Enabled       [  ON  ]  │
│  Selling Enabled      [  ON  ]  │
├─────────────────────────────────┤ ← Red separator
│     [  🛡️  PANIC  ]              │ ← Compact button
│  Emergency liquidation with     │
│  double-confirmation             │
└─────────────────────────────────┘
```

### Dashboard Header

Located in top-right header (always visible):

```
[ Layout ] [ 🛡️ PANIC ] [ Equity ] [ Day P/L ] [ Market Status ]
```

## 🧪 Testing Checklist

### ✅ Backend Testing

```bash
# 1. Test HWM tracking
firebase functions:shell
> pulse({})
# Check: systemStatus/risk_management.high_water_mark updated

# 2. Test drawdown calculation (manual Firestore edit)
# Set HWM high, run pulse with low equity
# Verify trading_enabled becomes false

# 3. Test emergency liquidation
> emergency_liquidate({ data: { confirmation: "LIQUIDATE_ALL" } })
# Verify all orders cancelled, positions closed
```

### ✅ Frontend Testing

```bash
# 1. Open dashboard
npm run dev

# 2. Click panic button (compact or main)
# Verify: First confirmation dialog appears
# Click: "Continue"
# Verify: Second confirmation dialog appears
# Click: "Cancel" (don't actually liquidate in dev!)

# 3. Test with actual liquidation (staging only!)
# Click through both confirmations
# Verify: Toast notification appears
# Verify: systemStatus/trading updated
```

### ✅ Integration Testing

```python
# tests/test_risk_integration.py

def test_kill_switch_blocks_signals(firestore_client):
    # Set trading_enabled = false
    firestore_client.collection("systemStatus").document("risk_management").set({
        "trading_enabled": False,
        "drawdown_percent": 0.06
    })
    
    # Try to generate signal
    signal = generate_signal_with_warm_cache(
        symbol="SPY",
        market_context="Market is bullish",
        db=firestore_client
    )
    
    # Verify: Signal is flat with drawdown reason
    assert signal.action == "flat"
    assert "Drawdown Recovery Mode" in signal.reason
```

## 🚨 Common Issues & Solutions

### Issue: Kill-switch not triggering

**Problem:** Trading continues despite 6% drawdown

**Solution:**
```bash
# Check Firestore document
firebase firestore get systemStatus/risk_management

# Verify pulse is running
firebase functions:log --only pulse

# Check for errors in logs
```

### Issue: Panic button not working

**Problem:** Button click does nothing or shows error

**Solution:**
```bash
# 1. Check Firebase Functions deployment
firebase deploy --only functions:emergency_liquidate

# 2. Verify frontend has functions SDK
# Check: frontend/src/firebase.ts exports 'functions'

# 3. Check browser console for errors
# Look for: CORS, authentication, or network errors
```

### Issue: Signal generation still works during drawdown

**Problem:** AI generates BUY signal when trading_enabled = false

**Solution:**
```python
# Verify the check is in place:
# backend/alpaca_signal_trader.py:generate_signal_with_warm_cache()
# Should have:
risk_doc = db.collection("systemStatus").document("risk_management").get()
if not risk_doc.get("trading_enabled"):
    return TradeSignal(action="flat", ...)
```

## 🔧 Configuration

### Change Drawdown Threshold

**Default: 5%**

To change to 3%:

```python
# functions/risk_manager.py
DEFAULT_DRAWDOWN_THRESHOLD = Decimal("0.03")  # 3%
```

Then redeploy:
```bash
firebase deploy --only functions
```

### Change Minimum Equity

**Default: $100**

To change to $500:

```python
# functions/risk_manager.py
MIN_EQUITY_FOR_TRACKING = Decimal("500.0")
```

## 📈 Monitoring Dashboard

### Key Metrics to Watch

1. **Current Drawdown**
   - Path: `systemStatus/risk_management.drawdown_percent`
   - Alert if > 0.04 (4%)

2. **Trading Status**
   - Path: `systemStatus/risk_management.trading_enabled`
   - Alert if false (kill-switch active)

3. **High Water Mark**
   - Path: `systemStatus/risk_management.high_water_mark`
   - Should trend upward over time

4. **Emergency Events**
   - Path: `systemStatus/trading.status`
   - Alert if "EMERGENCY_HALT"

### Firebase Console Queries

```javascript
// Check current risk state
db.collection('systemStatus').doc('risk_management').get()

// Check if any emergency liquidations
db.collection('systemStatus').doc('trading')
  .where('status', '==', 'EMERGENCY_HALT')
  .get()

// Get recent pulse updates
db.collection('alpacaAccounts').doc('snapshot').get()
```

## 🎓 Pro Tips

### For Conservative Traders (2% drawdown)

```python
# functions/risk_manager.py
DEFAULT_DRAWDOWN_THRESHOLD = Decimal("0.02")  # 2%
```

### For Aggressive Traders (10% drawdown)

```python
# functions/risk_manager.py
DEFAULT_DRAWDOWN_THRESHOLD = Decimal("0.10")  # 10%
```

### For SaaS Multi-Tenancy

Future enhancement - per-user thresholds:

```javascript
// tenants/{tenant_id}/settings/risk_management
{
  drawdown_threshold: 0.05,  // User's preference
  min_equity: 100.0,
  enabled: true
}
```

## 📞 Support

### Deployment
```bash
cd functions && firebase deploy --only functions:pulse,functions:emergency_liquidate
cd frontend && npm run build && firebase deploy --only hosting
```

### Logs
```bash
# Backend logs
firebase functions:log

# Filter by function
firebase functions:log --only pulse
firebase functions:log --only emergency_liquidate
```

### Manual Recovery

If you need to manually re-enable trading after kill-switch:

```python
from functions.risk_manager import manual_override_trading
from firebase_admin import firestore

db = firestore.client()
manual_override_trading(
    db=db,
    enabled=True,
    override_reason="Manual recovery - market conditions reviewed"
)
```

---

## 🎉 You're All Set!

The Risk Management Kill-Switch is now production-ready. It will:
- ✅ Automatically track your High Water Mark
- ✅ Monitor drawdown in real-time
- ✅ Disable trading if you hit 5% drawdown
- ✅ Block AI signals during recovery
- ✅ Give you a panic button for emergencies

**Remember:** The goal is to protect your capital and live to trade another day! 🛡️

---

**Questions?** Review `/docs/RISK_MANAGEMENT_KILLSWITCH.md` for full details.
