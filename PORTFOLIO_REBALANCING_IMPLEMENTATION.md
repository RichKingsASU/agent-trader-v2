# Portfolio Rebalancing Implementation

## Overview

This document describes the implementation of the Portfolio Rebalancing feature for AgentTrader, which allows users to define target portfolio allocations and automatically rebalance when asset weights drift more than 5% from their targets.

## Architecture

### Backend (Firebase Cloud Functions)

#### 1. Firestore Data Model

**Collection**: `userSettings/{uid}/allocation/{symbol}`

Documents store target allocations for each ticker:
- `symbol`: string (ticker symbol, e.g., "SPY")
- `target_percent`: number (target allocation percentage, e.g., 40 for 40%)
- `enabled`: boolean (whether this allocation is active)
- `created_at`: timestamp
- `updated_at`: timestamp

**Data Model Documentation**: Added to `FIRESTORE_DATA_MODEL.md`

#### 2. Cloud Functions

##### `execute_trade` (HTTPS Callable)

Location: `functions/main.py`

Executes individual trades via Alpaca API with risk management checks.

**Parameters**:
- `symbol`: string (ticker)
- `side`: "buy" | "sell"
- `qty`: number (quantity)
- `order_type`: string (default: "market")
- `time_in_force`: string (default: "day")

**Features**:
- Validates request parameters
- Checks risk management (trading enabled/disabled)
- Places orders via Alpaca API
- Returns order confirmation

##### `check_rebalance_drift` (HTTPS Callable)

Location: `functions/main.py`

Analyzes portfolio drift and automatically executes rebalancing trades.

**Algorithm**:

1. **Fetch Target Allocations**
   - Retrieves enabled target allocations from Firestore
   - Validates total allocations sum to ~100%

2. **Fetch Current Positions**
   - Gets account info and positions from Alpaca API
   - Calculates current portfolio value
   - Computes actual allocation percentages

3. **Calculate Drift**
   - For each target symbol, calculates: `drift = actual% - target%`
   - Identifies symbols with drift > 5% threshold

4. **Execute Rebalancing Trades**
   - For overweight positions (drift > +5%): SELL to reduce
   - For underweight positions (drift < -5%): BUY to increase
   - Calculates exact quantities based on target dollar values
   - Places market orders via Alpaca
   - Skips trades < $10 to avoid tiny orders

**Returns**:
```json
{
  "needs_rebalance": boolean,
  "drift_analysis": [
    {
      "symbol": "SPY",
      "target_percent": 40.0,
      "actual_percent": 46.5,
      "drift_percent": 6.5,
      "needs_rebalance": true,
      "action": "sell"
    }
  ],
  "trades_executed": [
    {
      "symbol": "SPY",
      "side": "sell",
      "qty": 10,
      "order_id": "abc123",
      "status": "accepted"
    }
  ],
  "portfolio_value": 100000.00,
  "message": "Rebalancing executed"
}
```

#### 3. Risk Integration

Both functions integrate with the existing risk management system:
- Check `systemStatus/risk_management` for `trading_enabled` flag
- Reject trades if system is in drawdown recovery mode
- Respect emergency kill-switch settings

### Frontend (React + TypeScript)

#### 1. Allocation Page Component

Location: `frontend/src/pages/Allocation.tsx`

**Features**:

1. **Target Allocation Management**
   - Add/remove target allocations
   - View all configured allocations
   - Real-time validation (totals should = 100%)

2. **Dual Pie Charts**
   - **Target Allocation Chart**: Shows desired portfolio distribution
   - **Actual Allocation Chart**: Shows current portfolio distribution after rebalancing check

3. **Drift Analysis Table**
   - Displays symbol-by-symbol comparison
   - Highlights drifts > 5% threshold
   - Shows required action (buy/sell)
   - Color-coded for easy identification

4. **Rebalancing Execution**
   - "Check & Rebalance" button triggers analysis
   - Automatically executes trades for drifted positions
   - Shows trade confirmation results

5. **Trades Executed Table**
   - Displays all rebalancing trades placed
   - Shows order IDs, quantities, and status

**UI Components Used**:
- `recharts`: Pie charts for visualizations
- `shadcn/ui`: Tables, Cards, Dialogs, Buttons, Inputs
- Real-time Firestore subscriptions for allocation data

#### 2. Navigation Integration

**Updated Files**:
- `frontend/src/App.tsx`: Added `/allocation` route
- `frontend/src/components/AppSidebar.tsx`: Added "Allocation" link to Trading section

## Key Features

### 1. Automatic Drift Detection

The system automatically calculates:
```
drift = (actual_allocation% - target_allocation%)
```

Example:
- Target: SPY = 40%
- Actual: SPY = 46.5%
- Drift: +6.5% → **SELL** (overweight)

### 2. Smart Trade Sizing

Calculates exact quantities needed:
```
target_value = (target_percent / 100) * portfolio_value
current_value = current_position_value
trade_value = |target_value - current_value|
qty = trade_value / current_price
```

### 3. Safety Features

- **5% Drift Threshold**: Only rebalance when drift > 5%
- **Minimum Trade Size**: Skips trades < $10
- **Risk Integration**: Respects kill-switch and drawdown limits
- **Validation**: Ensures target allocations sum to ~100%

### 4. Real-Time Updates

- Firestore listeners for allocation changes
- Instant UI updates when allocations modified
- Live drift analysis after rebalancing

## Usage Example

### 1. Configure Target Allocations

1. Navigate to `/allocation`
2. Click "Add Allocation"
3. Enter symbol (e.g., "SPY") and target percent (e.g., 40)
4. Repeat for other symbols
5. Ensure totals = 100%

Example configuration:
- SPY: 40%
- QQQ: 30%
- TLT: 20%
- GLD: 10%

### 2. Check & Rebalance

1. Click "Check & Rebalance" button
2. System analyzes current positions vs targets
3. If drift > 5%, automatically executes trades
4. View results in Drift Analysis and Trades Executed tables

### 3. Monitor Results

The system displays:
- Target vs Actual pie charts
- Drift percentage for each position
- Buy/Sell actions taken
- Order confirmations with IDs

## Security

- **Authentication Required**: All functions require Firebase Auth
- **User-Scoped Data**: Allocations stored per user ID
- **Risk Checks**: Integrated with existing risk management
- **Read-Only Positions**: Never modifies Alpaca data directly

## Testing Checklist

- [x] Backend functions compile successfully
- [x] Frontend components render without errors
- [x] Firestore data model documented
- [x] Navigation links added
- [x] Risk integration verified

### Manual Testing Steps

1. **Add Allocations**:
   - Add multiple symbols with target percentages
   - Verify totals validate (warning if ≠ 100%)
   - Delete allocations work correctly

2. **Drift Calculation**:
   - Run rebalance check
   - Verify drift calculations are accurate
   - Confirm 5% threshold detection

3. **Trade Execution**:
   - Check trades execute when drift > 5%
   - Verify correct buy/sell actions
   - Confirm order IDs returned

4. **Edge Cases**:
   - Portfolio value = 0
   - No target allocations configured
   - Trading disabled (risk management)
   - Very small positions (< $10)

## Future Enhancements

1. **Scheduled Rebalancing**: Cron job to check daily/weekly
2. **Rebalancing History**: Track past rebalancing events
3. **Custom Thresholds**: Allow per-symbol drift thresholds
4. **Tax-Aware Rebalancing**: Consider holding periods
5. **Partial Rebalancing**: Option to rebalance only specific positions
6. **Email Notifications**: Alert on rebalancing events
7. **Dry Run Mode**: Preview trades before execution

## Files Modified/Created

### Backend
- ✅ `functions/main.py` - Added `execute_trade` and `check_rebalance_drift` functions
- ✅ `FIRESTORE_DATA_MODEL.md` - Documented allocation collection schema

### Frontend
- ✅ `frontend/src/pages/Allocation.tsx` - New allocation page (465 lines)
- ✅ `frontend/src/App.tsx` - Added `/allocation` route
- ✅ `frontend/src/components/AppSidebar.tsx` - Added navigation link

## Dependencies

### Backend
- `firebase-functions`: Cloud Functions runtime
- `firebase-admin`: Firestore access
- `alpaca-trade-api`: Trading API client

### Frontend
- `recharts`: Pie chart visualization
- `firebase`: Firestore real-time subscriptions
- `shadcn/ui`: UI components
- `lucide-react`: Icons

## Deployment Notes

### Firebase Functions
```bash
cd functions
firebase deploy --only functions:execute_trade,functions:check_rebalance_drift
```

### Frontend
```bash
cd frontend
npm run build
firebase deploy --only hosting
```

### Environment Variables
Ensure these secrets are configured in Firebase:
- `ALPACA_KEY_ID`
- `ALPACA_SECRET_KEY`

## Monitoring

Monitor these metrics:
- Rebalancing frequency per user
- Trade success rate
- Drift magnitude distribution
- API error rates

## Support

For issues or questions:
1. Check Firebase Functions logs
2. Review Firestore security rules
3. Verify Alpaca API credentials
4. Check browser console for frontend errors

---

**Implementation Date**: December 30, 2025
**Status**: ✅ Complete
**Version**: 1.0
