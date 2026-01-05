# Phase 4.2: GEX Scraper & Logic Engine Implementation

## Overview

This document details the implementation of the GEX (Gamma Exposure) calculation engine that provides real-time "Market Weather" data to all trading strategies.

## Implementation Summary

### 1. GEX Engine (`functions/utils/gex_engine.py`)

**Purpose**: Calculate institutional-grade Net GEX from Alpaca option chains.

**Key Components**:

- **`calculate_net_gex(symbol: str)`**: Main function that:
  - Fetches 0DTE and 1DTE option chains for the symbol (e.g., SPY, QQQ)
  - Applies GEX formula for each strike:
    - **Call GEX** = Gamma × Open Interest × 100 × Spot Price
    - **Put GEX** = Gamma × Open Interest × 100 × Spot Price × (-1)
  - Aggregates to get **Total Net GEX**
  - Uses `Decimal` for fintech-grade precision (no floating-point drift)

- **`MarketRegime` Enum**:
  - `LONG_GAMMA` (Net GEX > 0): Market makers dampen volatility
  - `SHORT_GAMMA` (Net GEX < 0): Market makers amplify volatility
  - `NEUTRAL`: Balanced gamma exposure

- **`GEXResult` Dataclass**:
  - Contains: `net_gex`, `call_gex`, `put_gex`, `regime`, `spot_price`, `strikes_analyzed`, `timestamp`
  - Provides `to_dict()` for Firestore serialization

**Dependencies**:
- `alpaca-py>=0.8.0` (added to `functions/requirements.txt`)

**Precision**:
- All calculations use `decimal.Decimal` to prevent floating-point drift
- Results rounded to 2 decimal places using `ROUND_HALF_UP`

### 2. Firestore Integration (`functions/main.py`)

**New Scheduled Function**: `sync_market_regime()`

**Schedule**: Every 5 minutes (`*/5 * * * *`)

**Process**:
1. Calculates Net GEX for SPY using `calculate_net_gex()`
2. Determines market regime (LONG_GAMMA vs SHORT_GAMMA)
3. Updates Firestore document: `systemStatus/market_regime`

**Firestore Document Schema** (`systemStatus/market_regime`):
```python
{
    "net_gex": "12345.67",        # String for precision
    "call_gex": "45678.90",       # Total call GEX
    "put_gex": "-33333.23",       # Total put GEX (negative)
    "regime": "LONG_GAMMA",       # or "SHORT_GAMMA"
    "spot_price": "450.25",       # Current SPY price
    "strikes_analyzed": 150,       # Number of strikes processed
    "timestamp": <ServerTimestamp>,
    "symbol": "SPY"
}
```

**Error Handling**:
- Errors logged and stored in `systemStatus/market_regime_error`
- Does not crash if credentials missing (logs warning)

### 3. Strategy Framework Updates

#### BaseStrategy Classes

**Updated Files**:
- `functions/strategies/base_strategy.py` (primary)
- `functions/strategies/base.py` (legacy async version)

**New Parameter**: `regime: Optional[str]`

**Updated Signature**:
```python
def evaluate(
    self,
    market_data: Dict[str, Any],
    account_snapshot: Dict[str, Any],
    regime: Optional[str] = None  # NEW: Market regime
) -> TradingSignal:
```

**Regime Values**:
- `"LONG_GAMMA"`: Market stabilization (dampen allocation)
- `"SHORT_GAMMA"`: Accelerating volatility (increase allocation)
- `"NEUTRAL"`: Balanced gamma
- `None`: Regime data not available

### 4. GammaScalper Strategy Updates

**Updated File**: `functions/strategies/gamma_scalper.py`

**Key Changes**:

1. **`evaluate()` method now accepts `regime` parameter**
   - Fetched from Firestore in `main.py`
   - Passed to `_apply_gex_filter()`

2. **Enhanced `_apply_gex_filter()` method**:
   - Maps regime names: `"SHORT_GAMMA"` / `"negative"` → increase allocation
   - Maps regime names: `"LONG_GAMMA"` / `"positive"` → decrease allocation
   - Backward compatible with legacy `gex_status` field

3. **Dynamic Hedging Bands**:
   - **SHORT_GAMMA regime**: Allocation multiplied by `1.5x` (default)
     - Reasoning: "Accelerating volatility expected. Market makers amplify price movements."
   - **LONG_GAMMA regime**: Allocation multiplied by `0.5x` (default)
     - Reasoning: "Price stabilization expected. Market makers dampen price movements."

**Example Flow**:
```
Net Delta: 0.25 (exceeds threshold of 0.15)
→ Signal: SELL to reduce delta
→ Regime: SHORT_GAMMA (Net GEX = -5000)
→ Allocation Multiplier: 1.5x
→ Final Confidence: 0.75 (increased for volatility capture)
```

### 5. Integration with generate_trading_signal()

**Updated**: `functions/main.py` (callable function)

**New Step 2.5**: Fetch market regime from Firestore
```python
regime_doc = db.collection("systemStatus").document("market_regime").get()
regime = regime_data.get("regime")  # "LONG_GAMMA" or "SHORT_GAMMA"
```

**Updated Strategy Evaluation**:
```python
signal = strategy.evaluate(
    market_data=market_data,
    account_snapshot=account_snapshot,
    regime=regime  # NEW: Pass regime to strategy
)
```

## Usage

### 1. Setup Environment Variables

```bash
export ALPACA_API_KEY_ID="your_alpaca_key_id"
export ALPACA_API_SECRET_KEY="your_alpaca_secret_key"
```

Or configure in Firebase Functions secrets:
```bash
firebase functions:secrets:set ALPACA_API_KEY_ID
firebase functions:secrets:set ALPACA_API_SECRET_KEY
```

### 2. Deploy Functions

```bash
cd functions
firebase deploy --only functions:sync_market_regime
firebase deploy --only functions:generate_trading_signal
```

### 3. Monitor Market Regime

Query Firestore to see current regime:
```javascript
const regimeDoc = await firestore
  .collection('systemStatus')
  .doc('market_regime')
  .get();

console.log(regimeDoc.data());
// {
//   regime: "SHORT_GAMMA",
//   net_gex: "-12345.67",
//   timestamp: ...
// }
```

### 4. Frontend Integration

```typescript
// Display current market regime in UI
const MarketRegimeBadge = () => {
  const [regime, setRegime] = useState(null);
  
  useEffect(() => {
    const unsubscribe = firestore
      .collection('systemStatus')
      .doc('market_regime')
      .onSnapshot(doc => {
        setRegime(doc.data());
      });
    
    return unsubscribe;
  }, []);
  
  return (
    <div className={regime?.regime === 'SHORT_GAMMA' ? 'text-red-500' : 'text-green-500'}>
      {regime?.regime === 'SHORT_GAMMA' ? '⚡ High Volatility' : '🌤️ Stable Market'}
      <div className="text-sm">Net GEX: {regime?.net_gex}</div>
    </div>
  );
};
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Cloud Scheduler (Every 5 min)            │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              sync_market_regime() Function                  │
│  1. Fetch 0DTE/1DTE Option Chains from Alpaca             │
│  2. Calculate Net GEX (Decimal precision)                   │
│  3. Determine Regime (LONG_GAMMA vs SHORT_GAMMA)           │
│  4. Update Firestore: systemStatus/market_regime           │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    Firestore Document                       │
│           systemStatus/market_regime                        │
│  {                                                           │
│    net_gex: "-5000.00",                                     │
│    regime: "SHORT_GAMMA",                                   │
│    timestamp: ...                                           │
│  }                                                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│        generate_trading_signal() Callable Function          │
│  1. Read account snapshot                                   │
│  2. Read market data                                        │
│  3. **Fetch market regime from Firestore**                 │
│  4. Pass regime to strategy.evaluate()                     │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              GammaScalper.evaluate(regime)                  │
│  • Calculate net delta                                      │
│  • Apply delta hedge rule                                   │
│  • **Apply GEX filter based on regime**                    │
│    - SHORT_GAMMA → 1.5x allocation                         │
│    - LONG_GAMMA → 0.5x allocation                          │
│  • Return TradingSignal with confidence                    │
└─────────────────────────────────────────────────────────────┘
```

## Testing

### Manual Test: Calculate GEX

```python
from functions.utils.gex_engine import calculate_net_gex

result = calculate_net_gex(
    symbol="SPY",
    api_key_id="your_key",
    api_secret_key="your_secret"
)

print(f"Net GEX: {result.net_gex}")
print(f"Regime: {result.regime.value}")
print(f"Strikes Analyzed: {result.strikes_analyzed}")
```

### Expected Output

```
Calculating GEX for SPY...
SPY spot price: 450.25
Analyzing expirations: 2025-12-30 (0DTE), 2025-12-31 (1DTE)
Processed 2025-12-30: 75 strikes, Call GEX=50000.00, Put GEX=-35000.00
Processed 2025-12-31: 75 strikes, Call GEX=55000.00, Put GEX=-40000.00
GEX Calculation Complete: Net GEX=30000.00, Regime=LONG_GAMMA, Strikes=150

Net GEX: 30000.00
Regime: LONG_GAMMA
Strikes Analyzed: 150
```

### Test Strategy Evaluation with Regime

```python
from functions.strategies.gamma_scalper import GammaScalper

strategy = GammaScalper()
signal = strategy.evaluate(
    market_data={"symbol": "SPY", "price": 450.0, "greeks": {...}},
    account_snapshot={"equity": "10000", "positions": [...]},
    regime="SHORT_GAMMA"  # Test with high volatility regime
)

print(f"Action: {signal.signal_type.value}")
print(f"Confidence: {signal.confidence}")
print(f"Reasoning: {signal.reasoning}")
```

## Performance Considerations

1. **API Rate Limits**:
   - Alpaca options data API has rate limits
   - Running every 5 minutes provides good balance
   - Consider caching for very high-frequency strategies

2. **Computation Time**:
   - 0DTE + 1DTE chains: ~100-200 strikes
   - Calculation time: ~2-5 seconds
   - Firestore write: ~100ms
   - Total: **< 10 seconds per run**

3. **Precision**:
   - All calculations use `Decimal` (28 significant digits)
   - No floating-point drift
   - Suitable for institutional-grade accuracy

## Future Enhancements

1. **Multi-Symbol Support**:
   - Extend to QQQ, IWM, etc.
   - Store per-symbol regimes

2. **Historical GEX Tracking**:
   - Store time-series in Firestore subcollection
   - Enable backtesting with historical regimes

3. **Real-Time Streaming**:
   - Use Alpaca WebSocket for real-time option updates
   - Calculate GEX on every significant change

4. **Advanced Regime Detection**:
   - Add GEX momentum (rate of change)
   - Detect regime flips in real-time
   - Alert on critical levels (e.g., GEX crossing zero)

5. **Zero-GEX Level**:
   - Calculate the strike price where Net GEX = 0
   - This is a critical support/resistance level

## Troubleshooting

### Issue: "alpaca-py not installed"
**Solution**: Install dependency
```bash
cd functions
pip install alpaca-py>=0.8.0
```

### Issue: "Alpaca API credentials required"
**Solution**: Set environment variables
```bash
export ALPACA_API_KEY_ID="your_key"
export ALPACA_API_SECRET_KEY="your_secret"
```

### Issue: "No option chain data"
**Solution**: 
- Check if market is open
- Verify symbol has active options (e.g., SPY, QQQ)
- Check Alpaca data subscription tier

### Issue: "Market regime not found in Firestore"
**Solution**: 
- Manually trigger `sync_market_regime()` function
- Wait 5 minutes for scheduled run
- Check Cloud Functions logs for errors

## Conclusion

Phase 4.2 successfully implements:
- ✅ Real-time GEX calculation engine with Decimal precision
- ✅ Firestore integration for market regime storage
- ✅ BaseStrategy framework updated with regime parameter
- ✅ GammaScalper dynamic hedging based on regime
- ✅ Scheduled sync every 5 minutes
- ✅ Comprehensive error handling and logging

The system now provides institutional-grade "Market Weather" data to all trading strategies, enabling them to adapt to changing volatility regimes in real-time.
