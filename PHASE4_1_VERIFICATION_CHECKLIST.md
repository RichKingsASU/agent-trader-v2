# Phase 4.1 Shadow Mode - Verification Checklist

## Pre-Deployment Checklist

### Configuration & Setup
- [ ] Run `python scripts/init_shadow_mode_config.py`
- [ ] Verify `systemStatus/config` document exists in Firestore
- [ ] Confirm `is_shadow_mode` field is set to `true`
- [ ] Check Firestore security rules allow read/write access
- [ ] Verify `GOOGLE_APPLICATION_CREDENTIALS` is set correctly

### Code Review
- [ ] Backend imports correct: `Decimal`, `firebase_client`, `firestore_retry`
- [ ] All helper functions have proper docstrings
- [ ] Fail-safe logic returns `True` on errors
- [ ] Shadow trades use `Decimal` type for precision
- [ ] Frontend components properly imported in parent files
- [ ] No linting errors in modified files

### Backend Verification
- [ ] `get_shadow_mode_flag()` reads from Firestore
- [ ] `get_current_price()` fetches from `live_quotes` collection
- [ ] `create_shadow_trade()` logs to `shadowTradeHistory`
- [ ] `execute_trade()` has conditional logic for shadow/live modes
- [ ] All functions use proper error handling
- [ ] Logger statements are appropriate and informative

### Frontend Verification
- [ ] `ShadowToggle.tsx` component created and exported
- [ ] Component imported in `DashboardHeader.tsx`
- [ ] Toggle appears in dashboard header (before Panic Button)
- [ ] `ShadowModeIndicator.tsx` component created
- [ ] Indicator imported in `MainLayout.tsx`
- [ ] Firestore subscriptions properly set up

### UI/UX Verification
- [ ] Shadow toggle is visible and functional
- [ ] Switch shows correct state (ON/OFF)
- [ ] Badge displays "SIMULATED" when ON
- [ ] Badge displays "⚠️ LIVE" when OFF (pulsing)
- [ ] Watermark visible when shadow mode active
- [ ] Corner badge visible when shadow mode active
- [ ] Toast notifications work on toggle
- [ ] No visual glitches or layout issues

## Deployment Testing

### Smoke Tests
```bash
# 1. Backend service starts without errors
cd backend/strategy_service
uvicorn main:app --reload

# 2. Frontend builds successfully
cd frontend
npm run build

# 3. No import/module errors in console
npm run dev
```

### Integration Tests

#### Test 1: Shadow Mode Flag Retrieval
```python
# Test get_shadow_mode_flag()
from backend.strategy_service.routers.trades import get_shadow_mode_flag

# Should return True (default)
assert get_shadow_mode_flag() == True
```

#### Test 2: Price Fetching
```python
# Test get_current_price()
from backend.strategy_service.routers.trades import get_current_price

price = get_current_price("SPY")
# Should return Decimal > 0 if live_quotes populated
assert isinstance(price, Decimal)
```

#### Test 3: Shadow Trade Creation
```python
# Test create_shadow_trade()
# Create mock TradeRequest and TenantContext
# Execute create_shadow_trade()
# Verify shadowTradeHistory document created
# Verify all fields present and correct types
```

#### Test 4: Full Trade Execution Flow
```bash
# With shadow mode ON
curl -X POST http://localhost:8000/trades/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{
    "broker_account_id": "uuid",
    "strategy_id": "uuid",
    "symbol": "SPY",
    "instrument_type": "equity",
    "side": "buy",
    "order_type": "market",
    "notional": 10000
  }'

# Expected: Response with status="SHADOW_FILLED"
# Expected: Document in shadowTradeHistory collection
# Expected: NO call to Alpaca API
```

### UI Testing

#### Test 5: Toggle Functionality
- [ ] Open dashboard
- [ ] Locate shadow mode toggle
- [ ] Click to toggle OFF
- [ ] Verify badge changes to "⚠️ LIVE"
- [ ] Verify toast notification appears
- [ ] Check Firestore: `is_shadow_mode = false`
- [ ] Toggle back ON
- [ ] Verify badge changes to "SIMULATED"
- [ ] Check Firestore: `is_shadow_mode = true`

#### Test 6: Visual Indicators
- [ ] Shadow mode ON → Watermark visible
- [ ] Shadow mode ON → Corner badge visible
- [ ] Shadow mode OFF → Watermark hidden
- [ ] Shadow mode OFF → Corner badge hidden
- [ ] Watermark doesn't interfere with interactions
- [ ] Badge positioned correctly (top-right)

#### Test 7: Real-Time Updates
- [ ] Open dashboard in two browser tabs
- [ ] Toggle shadow mode in Tab 1
- [ ] Verify Tab 2 updates immediately (<1 second)
- [ ] Check both tabs show same state

### Error Handling Tests

#### Test 8: Missing Configuration
- [ ] Delete `systemStatus/config` document
- [ ] Execute trade
- [ ] Verify defaults to shadow mode
- [ ] Check logs for warning message
- [ ] Restore configuration

#### Test 9: Firestore Connection Error
- [ ] Temporarily break Firestore connection
- [ ] Execute trade
- [ ] Verify defaults to shadow mode (fail-safe)
- [ ] Check logs for error message
- [ ] Restore connection

#### Test 10: Missing Live Quote
- [ ] Execute trade for symbol not in `live_quotes`
- [ ] Verify shadow trade created with price = 0
- [ ] Check logs for warning message
- [ ] No crash or exception

### Performance Tests

#### Test 11: Latency Impact
- [ ] Measure trade execution time with shadow mode ON
- [ ] Measure trade execution time with shadow mode OFF
- [ ] Verify difference is < 20ms
- [ ] Check no significant performance degradation

#### Test 12: High Volume
- [ ] Execute 100 shadow trades rapidly
- [ ] Verify all logged to shadowTradeHistory
- [ ] Check Firestore quota usage
- [ ] Verify no rate limiting issues

### Security Tests

#### Test 13: Access Control
- [ ] Attempt to read `systemStatus/config` as unauthenticated user
- [ ] Verify access denied (or handle appropriately)
- [ ] Attempt to write as non-admin user
- [ ] Verify write denied (or handle appropriately)

#### Test 14: Data Validation
- [ ] Submit invalid trade request (missing fields)
- [ ] Verify proper error handling
- [ ] Check no partial shadow trades created
- [ ] Verify logs show validation error

## Post-Deployment Monitoring

### Day 1 Checklist
- [ ] Monitor backend logs for shadow mode flag reads
- [ ] Count shadow trades created (should be > 0 if strategies active)
- [ ] Verify no error spikes after deployment
- [ ] Check Firestore read/write usage
- [ ] Confirm UI toggle accessible to users

### Week 1 Checklist
- [ ] Review shadow trade history
- [ ] Compare shadow fills with actual market prices
- [ ] Verify Decimal precision maintained
- [ ] Check for any fail-safe activations
- [ ] Gather user feedback on UI/UX

### Performance Metrics
- [ ] Shadow mode toggle response time < 500ms
- [ ] Trade execution latency increase < 20ms
- [ ] Firestore read quota within limits
- [ ] No memory leaks from subscriptions
- [ ] UI remains responsive under load

## Rollback Plan

### If Critical Issue Detected

1. **Immediate Actions**
   ```bash
   # Set shadow mode to TRUE via Firestore Console
   # OR run:
   python scripts/init_shadow_mode_config.py
   ```

2. **Verify State**
   - Check dashboard toggle shows "SIMULATED"
   - Execute test trade
   - Verify logged to shadowTradeHistory
   - Confirm NO broker contact

3. **Rollback Code (if needed)**
   ```bash
   git checkout <previous-commit>
   # Redeploy backend
   # Redeploy frontend
   ```

4. **Post-Rollback**
   - Monitor logs for errors
   - Notify team of rollback
   - Document issue for post-mortem

## Documentation Checklist

- [x] `SHADOW_MODE.md` - Comprehensive documentation
- [x] `SHADOW_MODE_QUICK_REFERENCE.md` - Quick reference card
- [x] `PHASE4_1_SHADOW_MODE_SUMMARY.md` - Implementation summary
- [x] `PHASE4_1_VERIFICATION_CHECKLIST.md` - This checklist
- [x] Inline code comments and docstrings
- [x] README update (if applicable)

## Sign-Off

### Developer Sign-Off
- [ ] All code changes reviewed
- [ ] All tests passing
- [ ] No linting errors
- [ ] Documentation complete
- [ ] Ready for deployment

**Developer**: _________________  
**Date**: _________________

### QA Sign-Off
- [ ] All integration tests passed
- [ ] UI/UX verified
- [ ] Performance acceptable
- [ ] Security checks passed
- [ ] Ready for production

**QA Engineer**: _________________  
**Date**: _________________

### Product Sign-Off
- [ ] Feature meets requirements
- [ ] User experience acceptable
- [ ] Visual indicators clear
- [ ] Safety features verified
- [ ] Approved for release

**Product Manager**: _________________  
**Date**: _________________

## Additional Notes

### Known Limitations
1. Shadow mode is global (not per-strategy)
2. Fill prices use mid-price (may differ from actual fills)
3. No simulated slippage or partial fills
4. Shadow trades don't update positions

### Future Enhancements Planned
1. Per-strategy shadow mode
2. Shadow mode analytics dashboard
3. Scheduled auto-enable/disable
4. Shadow vs. live performance comparison
5. Shadow replay functionality

---

**Checklist Version**: 1.0  
**Last Updated**: December 30, 2025  
**Status**: Ready for verification
