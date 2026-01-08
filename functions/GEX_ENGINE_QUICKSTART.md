# GEX Engine Quick Start Guide

## Overview

The GEX (Gamma Exposure) Engine provides real-time "Market Weather" data to all trading strategies by calculating the net gamma exposure across the options market.

## What is GEX?

**Gamma Exposure (GEX)** measures how much market makers need to hedge their options positions:

- **Positive GEX (Bullish)**: Market makers are long gamma → they stabilize prices by selling rallies and buying dips
- **Negative GEX (Bearish)**: Market makers are short gamma → they amplify volatility by selling dips and buying rallies
- **Neutral GEX**: Balanced exposure → normal volatility expected

## Architecture

### 1. GEX Calculation Engine (`functions/utils/gex_engine.py`)

The core calculation logic:

```python
from functions.utils.gex_engine import calculate_net_gex

# Calculate GEX for SPY
gex_data = calculate_net_gex(symbol="SPY", api=alpaca_client)

# Access results
net_gex = gex_data["net_gex"]  # Total net GEX (string for fintech precision)
volatility_bias = gex_data["volatility_bias"]  # "Bullish", "Bearish", or "Neutral"
spot_price = gex_data["spot_price"]
option_count = gex_data["option_count"]
```

**Calculation Formula:**
- Call GEX = Gamma × OpenInterest × 100 × SpotPrice
- Put GEX = Gamma × OpenInterest × 100 × SpotPrice × (-1)
- Net GEX = Sum of all Call GEX + Sum of all Put GEX

### 2. Firestore Integration (1-Minute Heartbeat)

The `pulse` function in `functions/main.py` automatically:
1. Calculates GEX for SPY and QQQ every minute
2. Stores results in `systemStatus/market_regime`

**Firestore Document Structure:**
```
systemStatus/
  market_regime/
    {
      timestamp: ServerTimestamp,
      spy: {
        net_gex: "123456.78",
        volatility_bias: "Bullish",
        spot_price: "450.25",
        option_count: 1234,
        total_call_gex: "200000.00",
        total_put_gex: "-76543.22"
      },
      qqq: { ... },
      market_volatility_bias: "Bullish"
    }
```

### 3. Strategy Integration

#### BaseStrategy (`functions/strategies/base.py`)

All strategies now receive `regime_data` parameter:

```python
class MyStrategy(BaseStrategy):
    async def evaluate(
        self, 
        market_data: dict, 
        account_snapshot: dict,
        regime_data: Optional[Dict[str, Any]] = None
    ) -> dict:
        # Access GEX data
        if regime_data:
            spy_gex = regime_data.get("spy", {}).get("net_gex", "0")
            volatility_bias = regime_data.get("market_volatility_bias", "Unknown")
            
            # Adjust strategy based on market regime
            if volatility_bias == "Bearish":
                # Tighten risk limits, increase hedging frequency
                pass
        
        return {
            "action": "HOLD",
            "allocation": 0.0,
            "ticker": "SPY",
            "reasoning": f"Market regime: {volatility_bias}",
            "metadata": {"gex": spy_gex}
        }
```

#### GammaScalper Strategy

The GammaScalper automatically fetches GEX from Firestore and adjusts hedging thresholds:

```python
# In strategy.py
HEDGING_THRESHOLD = Decimal("0.15")  # Base threshold
HEDGING_THRESHOLD_NEGATIVE_GEX = Decimal("0.10")  # Tighter when GEX is negative

def _get_hedging_threshold() -> Decimal:
    gex = _fetch_gex_from_firestore()  # Reads from systemStatus/market_regime
    
    if gex is not None and gex < Decimal("0"):
        # Negative GEX: increase hedging frequency
        return HEDGING_THRESHOLD_NEGATIVE_GEX
    
    return HEDGING_THRESHOLD
```

## Usage Examples

### Example 1: Manual GEX Calculation

```python
from functions.utils.gex_engine import calculate_net_gex, get_market_regime_summary
import alpaca_trade_api as tradeapi

# Initialize Alpaca client
api = tradeapi.REST(key_id="...", secret_key="...", base_url="...")

# Calculate GEX
gex_data = calculate_net_gex(symbol="SPY", api=api)

# Print summary
summary = get_market_regime_summary(gex_data)
print(summary)

# Output:
# SPY Market Regime: BEARISH (Negative GEX = -1234567.89)
# Market makers are short gamma → expect volatility amplification
# They will sell dips and buy rallies, increasing volatility.
```

### Example 2: Reading GEX from Firestore (in Strategy)

```python
from google.cloud import firestore
from decimal import Decimal

db = firestore.Client()

# Read market regime data
doc = db.collection("systemStatus").document("market_regime").get()

if doc.exists:
    regime_data = doc.to_dict()
    
    spy_gex = Decimal(regime_data["spy"]["net_gex"])
    qqq_gex = Decimal(regime_data["qqq"]["net_gex"])
    
    print(f"SPY GEX: {spy_gex} ({regime_data['spy']['volatility_bias']})")
    print(f"QQQ GEX: {qqq_gex} ({regime_data['qqq']['volatility_bias']})")
```

### Example 3: Strategy Adaptation Based on GEX

```python
class AdaptiveStrategy(BaseStrategy):
    async def evaluate(self, market_data, account_snapshot, regime_data=None):
        allocation = 0.5  # Default allocation
        
        if regime_data:
            bias = regime_data.get("market_volatility_bias", "Neutral")
            
            if bias == "Bearish":
                # Reduce allocation in negative GEX regime
                allocation = 0.25
                reasoning = "Reduced allocation due to negative GEX (high volatility risk)"
            elif bias == "Bullish":
                # Increase allocation in positive GEX regime
                allocation = 0.75
                reasoning = "Increased allocation due to positive GEX (price stabilization)"
            else:
                reasoning = "Standard allocation (neutral GEX)"
        else:
            reasoning = "GEX data not available"
        
        return {
            "action": "BUY",
            "allocation": allocation,
            "ticker": "SPY",
            "reasoning": reasoning,
            "metadata": {
                "gex_bias": bias if regime_data else "Unknown"
            }
        }
```

## Monitoring & Debugging

### Check GEX Calculation Status

```bash
# View latest GEX data in Firestore
gcloud firestore documents get --collection-path=systemStatus --document-id=market_regime
```

### View GEX in Firebase Console

Navigate to:
```
Firestore Database → systemStatus → market_regime
```

### Check Pulse Function Logs

```bash
# View Cloud Function logs
gcloud functions logs read pulse --limit=50
```

Look for log messages:
- `"Calculating GEX for market regime..."`
- `"GEX stored successfully: SPY=... (Bullish/Bearish)"`
- `"Error calculating/storing GEX: ..."` (if errors occur)

## Testing

### Unit Test GEX Calculation

```python
# Run the test
pytest tests/test_gex_engine.py -v
```

### Smoke Test (Manual)

```python
# Create a test script: test_gex_manual.py
from functions.utils.gex_engine import calculate_net_gex
import alpaca_trade_api as tradeapi
import os

api = tradeapi.REST(
    key_id=os.getenv("APCA_API_KEY_ID"),
    secret_key=os.getenv("APCA_API_SECRET_KEY"),
    base_url=os.getenv("APCA_API_BASE_URL"),
    base_url="https://paper-api.alpaca.markets"
)

print("Testing GEX calculation...")
gex_data = calculate_net_gex(symbol="SPY", api=api)

print(f"Net GEX: {gex_data['net_gex']}")
print(f"Volatility Bias: {gex_data['volatility_bias']}")
print(f"Options Processed: {gex_data['option_count']}")
```

## Troubleshooting

### Issue: "No option chain data available"

**Cause**: Alpaca API may not have option chain data for the symbol or time period.

**Solution**:
1. Verify symbol supports options (SPY, QQQ do)
2. Check market hours (options data may be limited outside trading hours)
3. Verify Alpaca account has options data access

### Issue: GEX calculation returns 0.00

**Cause**: 
- No options with non-zero gamma and open interest
- API rate limiting
- Options data not available

**Solution**:
1. Check `option_count` in response (should be > 0)
2. Review error field in response
3. Check Alpaca API status

### Issue: Strategy not receiving regime_data

**Cause**: Pulse function may not be running or GEX calculation is failing.

**Solution**:
1. Verify pulse function is deployed and running
2. Check Firestore for `systemStatus/market_regime` document
3. Review Cloud Function logs for errors

## Performance Considerations

### API Rate Limits

- GEX calculation queries option chains (potentially hundreds of strikes)
- Runs every minute via pulse function
- Alpaca has rate limits (200 requests/minute for data endpoints)

**Optimization**:
- Calculation is done once per minute, not per-strategy
- Results cached in Firestore for all strategies to share
- Uses single API client to avoid connection overhead

### Firestore Costs

- 1 write per minute to `systemStatus/market_regime`
- Strategies read from Firestore (cached by Firebase SDK)
- Estimated: ~44,640 writes/month (~$0.27/month at $0.18 per 100k writes)

## Next Steps

1. **Deploy the pulse function**:
   ```bash
   firebase deploy --only functions:pulse
   ```

2. **Verify GEX data is being written**:
   - Check Firestore console for `systemStatus/market_regime`
   - Should update every minute

3. **Update your strategies** to use `regime_data` parameter

4. **Monitor performance** in production to ensure GEX data improves strategy results

## References

- [GEX Calculation Methodology](https://squeezemetrics.com/monitor/dix)
- [Gamma Hedging Explained](https://www.investopedia.com/terms/g/gamma-hedging.asp)
- [Options Greeks](https://www.investopedia.com/trading/getting-to-know-the-greeks/)
