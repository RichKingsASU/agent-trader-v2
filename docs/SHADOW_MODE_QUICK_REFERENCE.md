# Shadow Mode Quick Reference

## What is Shadow Mode?

Shadow Mode simulates trade execution without contacting the broker. All trades are logged with synthetic fill prices for analysis, but no actual orders are submitted.

## Quick Commands

### Initialize Configuration
```bash
python scripts/init_shadow_mode_config.py
```

### Check Current Status
```bash
# View in Firestore Console
# Collection: systemStatus
# Document: config
# Field: is_shadow_mode
```

### Toggle via Firestore
```javascript
db.collection('systemStatus').doc('config').set({
  is_shadow_mode: true  // true = shadow, false = live
}, { merge: true });
```

## Visual Indicators

| State | Toggle Badge | Watermark | Corner Badge |
|-------|-------------|-----------|--------------|
| Shadow Mode ON | 🟡 SIMULATED | Visible | Visible |
| Shadow Mode OFF | 🔴 ⚠️ LIVE | Hidden | Hidden |

## UI Location

**Dashboard Header** → Right Section → Before Panic Button

## Trade Behavior

### Shadow Mode ON (Default)
- ✅ Trade simulated using live quote mid-price
- ✅ Logged to `shadowTradeHistory` collection
- ✅ Status: `SHADOW_FILLED`
- ❌ NO broker contact
- ❌ NO actual order submission

### Shadow Mode OFF
- ❌ Trade submitted to broker (Alpaca)
- ✅ Logged to `paper_orders` collection
- ⚠️ Real market impact

## Fill Price Calculation

```python
# Shadow fill price (Decimal precision)
mid_price = (bid + ask) / 2

# Example: SPY bid=496.12, ask=496.14
fill_price = 496.13 (exact)

# Quantity from notional
quantity = notional / fill_price
```

## Collections

### `systemStatus/config`
```json
{
  "is_shadow_mode": true,
  "updated_at": "timestamp",
  "description": "Shadow mode config"
}
```

### `shadowTradeHistory/{shadow_id}`
```json
{
  "shadow_id": "uuid",
  "symbol": "SPY",
  "side": "buy",
  "quantity": "20.156612",
  "fill_price": "496.13",
  "status": "SHADOW_FILLED",
  "created_at": "timestamp"
}
```

## Fail-Safe Behavior

| Scenario | Result |
|----------|--------|
| Config document missing | ✅ Shadow mode ON |
| Field missing | ✅ Shadow mode ON |
| Firestore error | ✅ Shadow mode ON |
| Invalid value | ✅ Shadow mode ON |

**Default**: Always shadow mode for safety

## Safety Checklist

- [ ] Verify shadow mode toggle is visible in dashboard
- [ ] Check watermark appears when shadow mode is ON
- [ ] Test toggle switch functionality
- [ ] Execute test trade in shadow mode
- [ ] Verify shadow trade logged to `shadowTradeHistory`
- [ ] Confirm NO broker API call in logs
- [ ] Toggle to live mode and verify warning appears
- [ ] Re-enable shadow mode for safety

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Toggle not showing | Import `ShadowToggle` in `DashboardHeader.tsx` |
| Config error | Run `init_shadow_mode_config.py` |
| Trades still live | Verify `is_shadow_mode = true` in Firestore |
| Missing fill prices | Check `live_quotes` collection populated |
| UI loading forever | Check Firebase credentials in `.env` |

## Key Files

| Type | Path |
|------|------|
| Backend Logic | `backend/strategy_service/routers/trades.py` |
| UI Toggle | `frontend/src/components/ShadowToggle.tsx` |
| Visual Indicator | `frontend/src/components/ShadowModeIndicator.tsx` |
| Init Script | `scripts/init_shadow_mode_config.py` |
| Full Docs | `docs/SHADOW_MODE.md` |

## Best Practices

1. **Always start with shadow mode ON** for new deployments
2. **Test for 1+ days** before disabling shadow mode
3. **Monitor logs** for any anomalies
4. **Re-enable immediately** if issues detected
5. **Review shadow trades** before going live

## API Response

### Shadow Mode Trade
```json
{
  "id": "shadow_uuid",
  "status": "SHADOW_FILLED",
  "mode": "shadow",
  "fill_price": "496.13",
  "quantity": "20.156612",
  "message": "Trade executed in SHADOW MODE (simulation only, no broker contact)"
}
```

### Live Mode Trade
```json
{
  "id": "order_uuid",
  "status": "simulated",
  "symbol": "SPY",
  "side": "buy",
  "quantity": 20.0
}
```

## Emergency Procedures

### Immediately Enable Shadow Mode
1. Open Firebase Console
2. Navigate to `systemStatus/config`
3. Set `is_shadow_mode = true`
4. Save (updates propagate in <1 second)

### Or via UI
1. Locate shadow mode toggle in dashboard header
2. Click to enable (yellow SIMULATED badge)
3. Verify watermark appears

---

**For detailed documentation, see**: [SHADOW_MODE.md](./SHADOW_MODE.md)
