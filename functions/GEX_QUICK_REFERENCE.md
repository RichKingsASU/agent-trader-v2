# GEX Quick Reference Guide

## What is GEX?

**Gamma Exposure (GEX)** = Total gamma position of options dealers

```
GEX = Gamma × Open Interest × 100 × Underlying Price
```

- **Calls**: Positive GEX (dealers long gamma)
- **Puts**: Negative GEX (dealers short gamma)

---

## Market Regimes

| Regime | GEX | Dealer Behavior | Market Effect | Volatility |
|--------|-----|----------------|---------------|------------|
| **Positive GEX** | > 0 | Sell rallies, Buy dips | Stabilizing | ⬇️ Lower |
| **Negative GEX** | < 0 | Buy rallies, Sell dips | Amplifying | ⬆️ Higher |

---

## Trading Strategies by Regime

### ✅ Positive GEX (Stabilizing Market)

**Characteristics:**
- Mean reversion
- Range-bound
- Lower volatility

**Strategies:**
- Sell premium (iron condors, credit spreads)
- Fade extremes (contrarian scalping)
- Support/resistance trading
- Short straddles near zero gamma

**⚠️ Risk**: Watch for GEX flip to negative

---

### ⚠️ Negative GEX (Volatile Market)

**Characteristics:**
- Trending/directional
- Breakouts
- Higher volatility

**Strategies:**
- Buy volatility (straddles, strangles)
- Momentum/trend following
- Breakout trades
- Debit spreads (directional)

**⚠️ Risk**: Wider stops, reduce size

---

## Zero Gamma Strike

The strike where net GEX = 0

**Acts as:**
- Magnet (price gravitates toward it)
- Pivot (dealer behavior flips)
- Support/Resistance

**Above Zero Gamma:**
- Dealers stabilize → Sell rallies
- Fade moves, expect pullbacks

**Below Zero Gamma:**
- Dealers amplify → Buy rallies
- Momentum trades, cascades

---

## Firestore Data Structure

**Path:** `systemStatus/market_regime`

```json
{
  "regime": "positive_gex",           // or "negative_gex"
  "regime_label": "Stabilizing",      // or "Volatile"
  "weighted_gex": 89123456.0,
  
  "spy": {
    "gex": 102456789.0,
    "price": 580.50,
    "zero_gamma_strike": 575.0,
    "zero_gamma_pct_from_price": -0.95
  },
  
  "qqq": {
    "gex": 45678901.0,
    "price": 515.25,
    "zero_gamma_strike": 512.5,
    "zero_gamma_pct_from_price": -0.53
  },
  
  "timestamp": "2024-12-30T10:30:00Z"
}
```

---

## Quick Code Examples

### Read Regime (Frontend)

```typescript
import { doc, onSnapshot } from 'firebase/firestore';

onSnapshot(doc(db, 'systemStatus', 'market_regime'), (doc) => {
  const regime = doc.data();
  
  if (regime.regime === 'positive_gex') {
    console.log('📊 STABILIZING: Sell premium, fade extremes');
  } else {
    console.log('⚡ VOLATILE: Buy volatility, follow trends');
  }
});
```

### Read Regime (Backend)

```python
from firebase_admin import firestore

db = firestore.client()
doc = db.collection('systemStatus').document('market_regime').get()
regime = doc.to_dict()

if regime['regime'] == 'positive_gex':
    print("📊 STABILIZING: Mean reversion strategies")
else:
    print("⚡ VOLATILE: Momentum strategies")
```

---

## Manual Testing

```bash
# Test GEX calculation locally
cd /workspace/functions
python -m utils.gex_calculator
```

Expected output:
```
Starting GEX market regime update...
SPY: GEX=$102,456,789, Zero Gamma=575.0
QQQ: GEX=$45,678,901, Zero Gamma=512.5
Market Regime: Stabilizing (Weighted GEX: $89,123,456)
```

---

## Deployment

```bash
# Deploy GEX Cloud Function
cd /workspace/functions
firebase deploy --only functions:update_gex_market_regime
```

**Schedule:** Every 5 minutes (Cloud Scheduler)

---

## Monitoring Checklist

- [ ] Function deployed: `firebase functions:list`
- [ ] Scheduler running: `gcloud scheduler jobs list`
- [ ] Data in Firestore: `systemStatus/market_regime`
- [ ] Updated recently: `updated_at` < 10 minutes old
- [ ] No errors in logs: `firebase functions:log`

---

## Key Insights

1. **GEX > 0**: Market makers are net long gamma → they stabilize by fading moves
2. **GEX < 0**: Market makers are net short gamma → they amplify moves
3. **Zero Gamma Strike**: Critical pivot level where behavior flips
4. **Weighted GEX**: 70% SPY, 30% QQQ (SPY dominates)

---

## Common Patterns

### High Positive GEX
- VIX drops
- Tight ranges
- Boring grind higher
- **Strategy**: Sell OTM options

### High Negative GEX
- VIX spikes
- Wide swings
- Trending moves
- **Strategy**: Buy ATM straddles

### Regime Flip (Positive → Negative)
- Major shift in volatility regime
- Often happens around major support/resistance
- **Strategy**: Close mean-reversion trades, switch to momentum

### Price Near Zero Gamma
- Maximum uncertainty
- Potential breakout/breakdown
- **Strategy**: Wait for break, trade direction

---

## Resources

- **Documentation**: `/workspace/functions/README_GEX_SCRAPER.md`
- **Source Code**: `/workspace/functions/utils/gex_calculator.py`
- **Cloud Function**: `functions/main.py` → `update_gex_market_regime()`

---

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| No data in Firestore | Function not deployed | `firebase deploy --only functions:update_gex_market_regime` |
| Stale data (> 10 min) | Scheduler not running | Check `gcloud scheduler jobs list` |
| "Missing credentials" | Alpaca keys not set | Set `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`, and `APCA_API_BASE_URL` secrets |
| Empty option chain | Market closed | Expected outside 9:30 AM - 4:00 PM ET |

---

## API Limits

- **Alpaca**: Unlimited market data (live/paper accounts)
- **Cloud Functions**: 2M invocations/month (free tier)
- **Firestore**: 50K reads, 20K writes/day (free tier)

**GEX Scraper usage**: ~1,728 API calls/day (well within limits)
