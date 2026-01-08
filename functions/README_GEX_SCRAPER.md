# GEX (Gamma Exposure) Scraper & Market Regime Detector

## Overview

The GEX Scraper is an institutional-grade market analysis tool that calculates real-time Gamma Exposure levels from Alpaca options chains. It determines market regime (volatility expectations) by analyzing dealer gamma positioning in SPY and QQQ options.

## What is GEX?

**Gamma Exposure (GEX)** represents the total gamma position of options market makers and dealers. It's a key institutional metric for understanding how dealer hedging activity will impact market volatility.

### GEX Formula

```
GEX = Gamma × Open Interest × 100 × Underlying Price
```

For each option contract:
- **Gamma**: Rate of change of delta (Greek)
- **Open Interest**: Total outstanding contracts
- **100**: Multiplier (options control 100 shares each)
- **Underlying Price**: Current stock price

**Important**: Puts contribute negative GEX (dealers are short gamma on puts they sell).

### Market Regimes

#### 1. **Positive GEX (Net Long Gamma)** → Stabilizing Market

When total GEX > 0, market makers are net long gamma. They will:
- **Sell into rallies** (as delta increases, they need to reduce exposure)
- **Buy into dips** (as delta decreases, they need to add exposure)

**Result**: Stabilizing effect, lower volatility, mean-reverting price action

#### 2. **Negative GEX (Net Short Gamma)** → Volatile Market

When total GEX < 0, market makers are net short gamma. They will:
- **Buy into rallies** (as delta increases, they need to add exposure)
- **Sell into dips** (as delta decreases, they need to reduce exposure)

**Result**: Amplifying effect, higher volatility, trending price action

### Zero Gamma Strike

The "zero gamma" level is the strike price where net GEX crosses zero. This acts as a support/resistance level where dealer hedging behavior flips.

- **Above zero gamma**: Dealers stabilize the market
- **Below zero gamma**: Dealers amplify moves

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     Cloud Scheduler (Every 5 min)                │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│         Cloud Function: update_gex_market_regime()               │
│                  (functions/main.py)                             │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│            GEX Calculator Module                                 │
│         (functions/utils/gex_calculator.py)                      │
│                                                                   │
│  1. Fetch SPY & QQQ option chains from Alpaca                    │
│  2. Calculate GEX for each strike:                               │
│     • Calls: +Gamma × OI × 100 × Price                           │
│     • Puts:  -Gamma × OI × 100 × Price                           │
│  3. Sum total GEX by underlying                                  │
│  4. Find zero gamma strike                                       │
│  5. Determine weighted regime (70% SPY, 30% QQQ)                 │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Firestore: systemStatus/market_regime           │
│                                                                   │
│  {                                                                │
│    "regime": "positive_gex" | "negative_gex",                    │
│    "regime_label": "Stabilizing" | "Volatile",                   │
│    "weighted_gex": 123456789.0,                                  │
│    "spy": {                                                       │
│      "gex": 100000000.0,                                         │
│      "price": 580.50,                                            │
│      "zero_gamma_strike": 575.0,                                 │
│      "zero_gamma_pct_from_price": -0.95                          │
│    },                                                             │
│    "qqq": { ... },                                               │
│    "timestamp": "2024-12-30T10:30:00Z"                           │
│  }                                                                │
└─────────────────────────────────────────────────────────────────┘
```

## Installation & Setup

### 1. Environment Variables

Set the following environment variables in your Cloud Function configuration:

```bash
# Alpaca API Credentials
APCA_API_KEY_ID=<your-alpaca-api-key>
APCA_API_SECRET_KEY=<your-alpaca-secret-key>

# Firebase Project
FIREBASE_PROJECT_ID=<your-firebase-project-id>
```

### 2. Deploy Cloud Function

```bash
# From the /workspace/functions directory
firebase deploy --only functions:update_gex_market_regime
```

The function is configured to run every 5 minutes via Cloud Scheduler.

### 3. Verify Deployment

Check the logs:

```bash
firebase functions:log --only update_gex_market_regime
```

Expected output:
```
Starting GEX market regime update...
Calculating GEX for SPY...
SPY price: $580.50
Fetched 847 option snapshots for SPY (3 pages)
SPY GEX: Total=$102,456,789, Calls=$156,789,123, Puts=$-54,332,334, Zero Gamma Strike=575.0
Calculating GEX for QQQ...
QQQ price: $515.25
Fetched 723 option snapshots for QQQ (2 pages)
QQQ GEX: Total=$45,678,901, Calls=$67,890,123, Puts=$-22,211,222, Zero Gamma Strike=512.5
Market Regime: Stabilizing (Weighted GEX: $89,123,456)
Saved market regime to Firestore: positive_gex
GEX update complete: Regime=Stabilizing, Weighted GEX=$89,123,456
```

## Usage

### Reading Market Regime from Firestore

**Frontend (React/TypeScript):**

```typescript
import { doc, onSnapshot } from 'firebase/firestore';
import { db } from './firebase';

// Real-time listener
const unsubscribe = onSnapshot(
  doc(db, 'systemStatus', 'market_regime'),
  (doc) => {
    const regime = doc.data();
    
    console.log(`Market Regime: ${regime.regime_label}`);
    console.log(`Weighted GEX: $${regime.weighted_gex.toLocaleString()}`);
    console.log(`SPY Zero Gamma: ${regime.spy.zero_gamma_strike}`);
    
    if (regime.regime === 'positive_gex') {
      // Market is stabilizing - expect mean reversion
      console.log('Strategy: Fade extremes, sell rallies, buy dips');
    } else {
      // Market is volatile - expect trending
      console.log('Strategy: Trend following, momentum trades');
    }
  }
);
```

**Backend (Python):**

```python
from firebase_admin import firestore

db = firestore.client()
doc = db.collection('systemStatus').document('market_regime').get()

if doc.exists:
    regime = doc.to_dict()
    
    print(f"Market Regime: {regime['regime_label']}")
    print(f"Weighted GEX: ${regime['weighted_gex']:,.0f}")
    
    if regime['regime'] == 'positive_gex':
        # Stabilizing market - use mean reversion strategies
        print("Strategy: Contrarian, fade extremes")
    else:
        # Volatile market - use momentum strategies
        print("Strategy: Trend following, breakout trades")
```

### Manual Trigger (Testing)

You can manually trigger the GEX calculation for testing:

```bash
# From functions/ directory
python -m utils.gex_calculator
```

This will:
1. Calculate GEX for SPY and QQQ
2. Determine market regime
3. Save to Firestore
4. Print results to console

## Data Schema

### Firestore Document: `systemStatus/market_regime`

```typescript
interface MarketRegime {
  regime: 'positive_gex' | 'negative_gex';
  regime_label: 'Stabilizing' | 'Volatile';
  description: string;
  weighted_gex: number;
  
  spy: {
    gex: number;                    // Total SPY GEX
    price: number;                  // Current SPY price
    zero_gamma_strike: number | null;  // Zero gamma level
    zero_gamma_pct_from_price: number | null;  // % distance from ATM
  };
  
  qqq: {
    gex: number;
    price: number;
    zero_gamma_strike: number | null;
    zero_gamma_pct_from_price: number | null;
  };
  
  timestamp: string;                // ISO 8601 timestamp
  updated_at: Timestamp;            // Firestore server timestamp
  source: 'gex_calculator';
  version: '1.0';
}
```

## Trading Strategies Using GEX

### Positive GEX Regime (Stabilizing)

**Characteristics:**
- Lower realized volatility
- Mean-reverting price action
- Range-bound trading

**Strategies:**
- Iron condors (sell OTM calls and puts)
- Credit spreads near zero gamma level
- Contrarian scalping (fade moves)
- Sell premium in low-volatility conditions

**Risk Management:**
- Watch for regime flip (GEX crossing zero)
- Tighter stops when approaching zero gamma
- Reduce position size if volatility spikes

### Negative GEX Regime (Volatile)

**Characteristics:**
- Higher realized volatility
- Trending, directional moves
- Breakouts and gap fills

**Strategies:**
- Long straddles/strangles (buy volatility)
- Momentum/trend following
- Breakout trades with wide stops
- Debit spreads for directional bets

**Risk Management:**
- Wider stops (expect whipsaws)
- Size down to manage volatility
- Watch for regime flip back to positive

### Zero Gamma Strike Trading

The zero gamma level acts as a **magnet and pivot**:

**Above Zero Gamma:**
- Expect pullbacks (dealers sell rallies)
- Fade extreme moves
- Use support levels

**Below Zero Gamma:**
- Expect acceleration (dealers buy rallies)
- Momentum trades
- Break support = cascade lower

## Monitoring & Alerts

### Firestore Security Rules

Ensure your Firestore rules allow reads for authenticated users:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /systemStatus/market_regime {
      allow read: if request.auth != null;  // Authenticated users
      allow write: if false;  // Only Cloud Functions can write
    }
  }
}
```

### Cloud Monitoring Alerts

Set up alerts for:

1. **Function Errors**: Alert if `update_gex_market_regime` fails
2. **Stale Data**: Alert if `systemStatus/market_regime.updated_at` > 10 minutes old
3. **Regime Changes**: Alert when `regime` flips (positive → negative or vice versa)

Example alert (Cloud Console → Monitoring → Alerting):

```yaml
condition:
  displayName: "GEX Regime Changed"
  conditionThreshold:
    filter: 'resource.type="cloud_function" AND resource.labels.function_name="update_gex_market_regime"'
    comparison: COMPARISON_GT
    thresholdValue: 0
    duration: 60s
```

## Performance & Costs

### API Usage

- **Alpaca API calls per run**: 6 requests (2 underlyings × 3 requests each)
  - 1 request for underlying price
  - 1+ requests for option chain (paginated)
  
- **Frequency**: Every 5 minutes = 288 runs/day

**Total daily API calls**: ~1,728 requests/day

This is well within Alpaca's free tier limits (unlimited market data for live/paper accounts).

### Cloud Function Costs

- **Invocations**: 288/day = 8,640/month
- **Memory**: 256MB (default)
- **Runtime**: ~5-10 seconds per invocation

**Estimated cost**: ~$0.20/month (within free tier)

### Firestore Costs

- **Writes**: 288/day = 8,640/month
- **Reads**: Depends on client usage (real-time listeners)

**Estimated cost**: ~$0.10/month (within free tier)

## Troubleshooting

### "Missing Alpaca credentials" Error

**Solution**: Set `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in Cloud Function secrets.

```bash
firebase functions:secrets:set APCA_API_KEY_ID
firebase functions:secrets:set APCA_API_SECRET_KEY
```

### "No option snapshots found" Warning

**Cause**: Alpaca returned empty option chain (market closed, low liquidity).

**Solution**: This is expected outside market hours (9:30 AM - 4:00 PM ET). The function will retry on next run.

### "Failed to fetch price" Error

**Cause**: Network error or invalid symbol.

**Solution**: Check Alpaca API status and verify symbols (SPY, QQQ) are valid.

### Stale Data (updated_at > 10 minutes old)

**Cause**: Function not running or erroring silently.

**Solution**: 
1. Check Cloud Scheduler: `gcloud scheduler jobs list`
2. Check function logs: `firebase functions:log --only update_gex_market_regime`
3. Verify function is deployed: `firebase functions:list`

## Advanced Configuration

### Custom Symbols

To analyze different underlyings (e.g., AAPL, TSLA), modify the function call:

```python
# In functions/main.py
regime_data = calculate_and_update_gex(db, symbols=["AAPL", "TSLA"])
```

### Custom Schedule

To change the update frequency, modify the schedule:

```python
# Every 1 minute
@scheduler_fn.on_schedule(schedule="* * * * *", ...)

# Every 15 minutes
@scheduler_fn.on_schedule(schedule="*/15 * * * *", ...)

# Every hour
@scheduler_fn.on_schedule(schedule="0 * * * *", ...)
```

Cron format: `minute hour day_of_month month day_of_week`

### Custom Weighting

To change the SPY/QQQ weighting, modify `determine_market_regime()`:

```python
# In functions/utils/gex_calculator.py
# 50/50 weighting instead of 70/30
spy_weight = 0.5
qqq_weight = 0.5
```

## References

### Academic Papers
- Dealers and Market Volatility (Ahn et al., 2022)
- Gamma Exposure and Realized Volatility (Kuepper & Van Asch, 2021)

### Industry Resources
- [SpotGamma](https://www.spotgamma.com/) - Commercial GEX platform
- [SqueezeMetrics](https://squeezemetrics.com/) - Dark Index (DIX) and GEX data
- [Tradytics](https://www.tradytics.com/) - Options flow and GEX analysis

### Alpaca Documentation
- [Options Data API](https://alpaca.markets/docs/api-references/market-data-api/options-data/)
- [Options Snapshots](https://alpaca.markets/docs/api-references/market-data-api/options-data/snapshots/)
- [Options Greeks](https://alpaca.markets/docs/api-references/market-data-api/options-data/greeks/)

## Support

For issues or questions:

1. Check function logs: `firebase functions:log --only update_gex_market_regime`
2. Verify Firestore data: Firebase Console → Firestore → `systemStatus/market_regime`
3. Test manually: `python -m utils.gex_calculator`
4. Open an issue in the project repository

## License

This GEX scraper is part of the AgentTrader platform and follows the same license as the main project.
