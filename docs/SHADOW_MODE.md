# Shadow Mode Implementation - Phase 4.1

## Overview

**Shadow Mode** is a safety feature that allows the trading system to simulate trade execution without contacting the broker (Alpaca). When Shadow Mode is enabled, all trades are logged to Firestore for analysis, but no actual orders are submitted to the market.

This feature is critical for:
- Testing new strategies in production without risk
- Debugging trading logic with real market data
- Gradual rollout of new features
- Safety during system maintenance

## Architecture

### Components

1. **Backend Logic** (`backend/strategy_service/routers/trades.py`)
   - `get_shadow_mode_flag()`: Reads configuration from Firestore
   - `create_shadow_trade()`: Creates synthetic orders with SHADOW_FILLED status
   - `execute_trade()`: Main execution function with conditional logic

2. **Frontend Toggle** (`frontend/src/components/ShadowToggle.tsx`)
   - Real-time Firestore subscription for configuration
   - High-visibility switch in dashboard header
   - Toast notifications on mode changes

3. **Visual Indicators** (`frontend/src/components/ShadowModeIndicator.tsx`)
   - Watermark overlay: "SIMULATED ENVIRONMENT"
   - Corner badge with shadow mode status
   - Only displayed when shadow mode is active

4. **Configuration** (`systemStatus/config` Firestore document)
   - `is_shadow_mode`: Boolean flag (default: `true`)
   - `updated_at`: Timestamp of last change
   - `description`: Documentation string

5. **History Collection** (`shadowTradeHistory` Firestore collection)
   - Logs all shadow trades with synthetic fill data
   - Uses Decimal precision for accurate P&L tracking

## Fail-Safe Design

The system implements multiple fail-safe mechanisms:

1. **Default to Shadow Mode**: On any error reading the configuration flag, the system defaults to `is_shadow_mode = true`
2. **Backend Validation**: Always checks flag before executing trades
3. **Frontend Safeguards**: Shows warnings when disabling shadow mode
4. **Precision**: Uses `Decimal` type for all price calculations to ensure accuracy

## Setup & Configuration

### Initial Setup

Run the initialization script to create the configuration document:

```bash
# Set up credentials (if not already done)
gcloud auth application-default login
export FIREBASE_PROJECT_ID=your-project-id

# Initialize shadow mode configuration
python scripts/init_shadow_mode_config.py
```

This script:
- Creates `systemStatus/config` document if it doesn't exist
- Sets `is_shadow_mode` to `true` by default
- Shows current configuration status
- Prompts before updating existing configuration

### Manual Configuration

You can also manually set the shadow mode flag in Firestore:

```javascript
// Using Firebase Console or Admin SDK
db.collection('systemStatus').doc('config').set({
  is_shadow_mode: true,  // true = shadow mode ON, false = live trading
  updated_at: new Date(),
  description: 'Shadow mode controls whether trades are simulated (true) or executed live (false)'
}, { merge: true });
```

## Usage

### Toggling Shadow Mode

#### Via UI (Recommended)

1. Navigate to the dashboard
2. Locate the **Shadow Mode** toggle in the header (next to the Panic Button)
3. Click the switch to toggle between modes:
   - **ON** (Yellow badge): Trades are simulated
   - **OFF** (Red badge, pulsing): Trades are submitted to broker

#### Via Firestore Console

1. Open Firebase Console
2. Navigate to Firestore Database
3. Find document: `systemStatus/config`
4. Update field: `is_shadow_mode`
   - `true`: Enable shadow mode (safe)
   - `false`: Disable shadow mode (live trading)

### Monitoring Shadow Trades

Shadow trades are logged to the `shadowTradeHistory` collection:

```javascript
// Query shadow trades
db.collection('shadowTradeHistory')
  .orderBy('created_at', 'desc')
  .limit(50)
  .get()
```

Each shadow trade document contains:
- `shadow_id`: Unique identifier
- `symbol`: Ticker symbol
- `side`: 'buy' or 'sell'
- `quantity`: Calculated quantity (as Decimal string)
- `fill_price`: Simulated fill price from live quotes
- `status`: Always "SHADOW_FILLED"
- `created_at`: Timestamp
- Additional metadata (strategy_id, broker_account_id, etc.)

## Visual Indicators

When shadow mode is active, users see:

1. **Header Toggle**: Yellow "SIMULATED" badge next to switch
2. **Watermark**: Large diagonal "SIMULATED ENVIRONMENT" text overlay (subtle, 5% opacity)
3. **Corner Badge**: Top-right badge showing "Shadow Mode Active"

These indicators disappear when shadow mode is disabled.

## Trade Execution Flow

### Shadow Mode Enabled (`is_shadow_mode = true`)

```
User triggers trade
    ↓
execute_trade() called
    ↓
get_shadow_mode_flag() → TRUE
    ↓
Risk check (always performed)
    ↓
[If risk check passes]
    ↓
get_current_price(symbol) from live_quotes
    ↓
create_shadow_trade()
    - Generate synthetic order with shadow_id
    - Calculate fill price using mid-price (bid + ask) / 2
    - Calculate quantity with Decimal precision
    - Set status = "SHADOW_FILLED"
    - Log to shadowTradeHistory collection
    ↓
Return shadow trade result (NO broker contact)
```

### Shadow Mode Disabled (`is_shadow_mode = false`)

```
User triggers trade
    ↓
execute_trade() called
    ↓
get_shadow_mode_flag() → FALSE
    ↓
Risk check (always performed)
    ↓
[If risk check passes]
    ↓
Submit order to Alpaca broker
    ↓
Log to paper_orders collection
    ↓
Return broker response
```

## Fill Price Calculation

Shadow trades use real-time market data for accurate simulation:

1. **Fetch Live Quote**: Read from `live_quotes/{symbol}` collection
2. **Calculate Mid-Price**: `(bid + ask) / 2`
3. **Fallback**: If bid/ask unavailable, use `price` field
4. **Precision**: All calculations use Python's `Decimal` type
5. **Quantity**: If not provided, calculate from `notional / fill_price`

Example:
```python
# If SPY bid = 496.12, ask = 496.14
fill_price = (Decimal("496.12") + Decimal("496.14")) / Decimal("2")
# fill_price = 496.13 (exact)

# Calculate quantity from $10,000 notional
quantity = Decimal("10000") / fill_price
# quantity = 20.15661... shares
```

## Best Practices

### Development & Testing
- **Always start with shadow mode enabled** when deploying new strategies
- Test with shadow mode for at least 1 trading day before going live
- Review `shadowTradeHistory` to verify strategy behavior

### Production Deployment
1. Deploy with `is_shadow_mode = true` (default)
2. Monitor shadow trades for 1-3 days
3. Verify P&L calculations and fill prices
4. Gradually disable shadow mode for limited trading
5. Monitor closely after disabling

### Safety Protocols
- **Never disable shadow mode globally** without testing first
- Use shadow mode during market open when testing new features
- Re-enable shadow mode immediately if anomalies are detected
- Keep shadow mode logs for post-trade analysis

## Troubleshooting

### Issue: Shadow mode toggle not appearing
**Solution**: Check that ShadowToggle is imported in DashboardHeader:
```tsx
import { ShadowToggle } from "@/components/ShadowToggle";
```

### Issue: Trades still executing in shadow mode
**Solution**: 
1. Verify Firestore `systemStatus/config` document exists
2. Check that `is_shadow_mode` field is set to `true`
3. Review backend logs for error messages
4. Restart backend service to pick up configuration changes

### Issue: "Configuration Error" toast appears
**Solution**: 
1. Check Firebase credentials are configured
2. Verify Firestore security rules allow read access to `systemStatus/config`
3. Run `python scripts/init_shadow_mode_config.py` to create document

### Issue: Shadow trades missing fill prices
**Solution**:
1. Verify `live_quotes` collection is being populated
2. Check that market data ingestion is running
3. Review logs for errors in `get_current_price()` function

### Issue: UI shows "Loading..." indefinitely
**Solution**:
1. Check browser console for Firebase connection errors
2. Verify Firebase config in `.env` file
3. Test Firestore connection manually
4. Clear browser cache and reload

## Security Considerations

### Firestore Rules

Ensure appropriate security rules for the shadow mode configuration:

```javascript
// systemStatus/config: Admins can read/write
match /systemStatus/{document} {
  allow read: if request.auth != null;
  allow write: if request.auth != null && 
                  get(/databases/$(database)/documents/users/$(request.auth.uid)).data.role == 'admin';
}

// shadowTradeHistory: Authenticated users can read, system can write
match /shadowTradeHistory/{tradeId} {
  allow read: if request.auth != null;
  allow create: if request.auth != null;
  allow update, delete: if false;  // Immutable
}
```

### Role-Based Access

Consider implementing role-based access control for the shadow mode toggle:
- **Admins**: Can toggle shadow mode
- **Traders**: Can view shadow mode status
- **Viewers**: Read-only access to shadow trade history

## Architecture Verification Checklist

- [x] **Fail-Safe**: Error reading `is_shadow_mode` flag defaults to SHADOW MODE = TRUE
- [x] **Precision**: Shadow fills calculated using `Decimal` type for accurate P&L
- [x] **UI Integration**: High-visibility toggle in dashboard header
- [x] **Visual Warning**: Watermark and badge when shadow mode is active
- [x] **Immutable Logs**: Shadow trades logged to dedicated `shadowTradeHistory` collection
- [x] **Real-Time Updates**: UI subscribes to Firestore for instant mode changes
- [x] **Risk Integration**: Risk checks performed regardless of shadow mode
- [x] **Documentation**: Comprehensive docs and inline comments

## Testing

### Manual Testing Checklist

1. **Initial Setup**
   - [ ] Run `init_shadow_mode_config.py` script
   - [ ] Verify `systemStatus/config` document created
   - [ ] Confirm `is_shadow_mode = true` by default

2. **UI Testing**
   - [ ] Shadow toggle appears in dashboard header
   - [ ] Toggle shows "SIMULATED" badge when ON
   - [ ] Toggle shows "⚠️ LIVE" badge when OFF
   - [ ] Watermark visible when shadow mode active
   - [ ] Corner badge visible when shadow mode active

3. **Trade Execution Testing**
   - [ ] Execute test trade with shadow mode ON
   - [ ] Verify trade logged to `shadowTradeHistory`
   - [ ] Confirm NO order sent to Alpaca
   - [ ] Check fill price matches live quote mid-price
   - [ ] Toggle shadow mode OFF
   - [ ] Execute test trade with shadow mode OFF
   - [ ] Verify order sent to broker (or paper_orders collection)

4. **Error Handling**
   - [ ] Delete `systemStatus/config` document
   - [ ] Execute trade → should default to shadow mode
   - [ ] Check logs for warning message
   - [ ] Restore configuration document

5. **Performance Testing**
   - [ ] Execute 10 shadow trades in rapid succession
   - [ ] Verify all logged correctly
   - [ ] Check no Firestore write quota issues
   - [ ] Confirm UI remains responsive

### Automated Testing

```python
# Test shadow mode flag retrieval
def test_get_shadow_mode_flag():
    # Test with flag = True
    # Test with flag = False
    # Test with missing document (should return True)
    # Test with missing field (should return True)
    # Test with Firestore error (should return True)

# Test shadow trade creation
def test_create_shadow_trade():
    # Test with valid trade request
    # Test quantity calculation
    # Test fill price from live quotes
    # Test Decimal precision

# Test execute_trade with shadow mode
def test_execute_trade_shadow_mode():
    # Mock is_shadow_mode = True
    # Execute trade
    # Assert no Alpaca API call
    # Assert shadowTradeHistory entry created
```

## Future Enhancements

### Potential Features
1. **Per-Strategy Shadow Mode**: Enable/disable shadow mode per strategy
2. **Scheduled Shadow Mode**: Auto-enable during specific hours
3. **Shadow Mode Analytics**: Dashboard showing shadow vs. live trade performance
4. **Shadow Replay**: Replay shadow trades as live orders
5. **A/B Testing**: Run same strategy in both modes simultaneously
6. **Shadow Mode Alerts**: Notify when shadow trades would have exceeded risk limits

### Integration Ideas
- **Slack Notifications**: Alert when shadow mode changes
- **Audit Log**: Track all shadow mode toggles with user attribution
- **Shadow P&L Dashboard**: Show what P&L would have been if trades were live
- **Shadow vs. Live Diff**: Compare shadow trade fills with actual broker fills

## References

- [FIRESTORE_DATA_MODEL.md](./FIRESTORE_DATA_MODEL.md): Data model for live quotes
- [RISK_MANAGEMENT_KILLSWITCH.md](./RISK_MANAGEMENT_KILLSWITCH.md): Emergency controls
- [ARCHITECTURE_VERIFICATION_CHECKLIST.md](../ARCHITECTURE_VERIFICATION_CHECKLIST.md): System architecture

## Support

For questions or issues with Shadow Mode:
1. Check this documentation
2. Review backend logs for error messages
3. Verify Firestore configuration
4. Test with initialization script

---

**Last Updated**: December 30, 2025  
**Version**: 1.0  
**Status**: Production Ready
