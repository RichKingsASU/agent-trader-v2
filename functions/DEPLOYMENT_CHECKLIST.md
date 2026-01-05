# Phase 4.2 GEX Engine - Deployment Checklist

## ✅ Pre-Deployment Verification

### 1. Code Quality
- [x] All Python files compile without syntax errors
- [x] No linter errors in modified files
- [x] All imports are valid
- [x] Decimal precision used for all financial calculations

### 2. Files Created/Modified

#### Created Files
- [x] `functions/utils/__init__.py`
- [x] `functions/utils/gex_engine.py`
- [x] `functions/GEX_ENGINE_QUICKSTART.md`
- [x] `functions/test_gex_engine.py`
- [x] `functions/example_gex_usage.py`
- [x] `PHASE4_2_GEX_IMPLEMENTATION_SUMMARY.md`
- [x] `functions/DEPLOYMENT_CHECKLIST.md` (this file)

#### Modified Files
- [x] `functions/main.py` - Added GEX calculation to pulse function
- [x] `functions/strategies/base.py` - Added regime_data parameter
- [x] `backend/strategy_runner/examples/gamma_scalper_0dte/strategy.py` - Implemented Firestore GEX fetch

### 3. Functional Requirements
- [x] GEX calculation engine implemented
- [x] Fetches 0DTE and 1DTE option chains
- [x] Calculates Call GEX and Put GEX for each strike
- [x] Aggregates to Net GEX
- [x] Uses Decimal for precision
- [x] Integrated into 1-minute pulse function
- [x] Stores results in `systemStatus/market_regime`
- [x] BaseStrategy supports regime_data parameter
- [x] GammaScalper reads GEX and adjusts hedging

### 4. Testing
- [x] Unit tests created (`test_gex_engine.py`)
- [x] Example usage script created
- [x] Comprehensive documentation written

## 🚀 Deployment Steps

### Step 1: Install Dependencies (if needed)

```bash
cd /workspace/functions

# Check if requirements.txt includes necessary packages
cat requirements.txt

# Should include:
# - alpaca-trade-api
# - firebase-admin
# - firebase-functions
# - google-cloud-secret-manager>=2.16.0
```

### Step 2: Configure Alpaca API Keys

Ensure at least one user has Alpaca keys configured in Firestore:

```
users/{userId}/secrets/alpaca
  {
    "key_id": "...",
    "secret_key": "...",
    "base_url": "https://paper-api.alpaca.markets"
  }
```

### Step 3: Deploy Cloud Functions

```bash
cd /workspace/functions

# Deploy the pulse function
firebase deploy --only functions:pulse

# Expected output:
# ✔  functions[pulse(...)] Successful update operation.
```

### Step 4: Verify Deployment

```bash
# Check function logs (wait 1-2 minutes for first execution)
gcloud functions logs read pulse --limit=50

# Look for:
# - "Calculating GEX for market regime..."
# - "GEX stored successfully: SPY=... (Bullish/Bearish)"
```

### Step 5: Verify Firestore Data

```bash
# Check if GEX data is being written
gcloud firestore documents get \
  --collection-path=systemStatus \
  --document-id=market_regime

# Expected fields:
# - timestamp
# - spy.net_gex
# - spy.volatility_bias
# - qqq.net_gex
# - qqq.volatility_bias
# - market_volatility_bias
```

Or use Firebase Console:
1. Navigate to Firestore Database
2. Open `systemStatus` collection
3. View `market_regime` document
4. Verify data is updating every minute

### Step 6: Monitor for Errors

```bash
# Real-time log streaming
gcloud functions logs tail pulse

# Watch for any errors in GEX calculation
```

## 🧪 Post-Deployment Testing

### Test 1: Verify GEX Calculation

```bash
# Run example script
cd /workspace
export ALPACA_KEY_ID="your_key"
export ALPACA_SECRET_KEY="your_secret"
python3 functions/example_gex_usage.py
```

### Test 2: Verify Strategy Integration

Check that GammaScalper can fetch GEX:

```python
# In Python REPL or test script
from backend.strategy_runner.examples.gamma_scalper_0dte.strategy import _fetch_gex_from_firestore

gex_value = _fetch_gex_from_firestore()
print(f"GEX Value: {gex_value}")
# Should print a Decimal value or None
```

### Test 3: Run Unit Tests

```bash
cd /workspace
pytest functions/test_gex_engine.py -v

# All tests should pass (except the live integration test which is skipped)
```

## 📊 Monitoring Dashboard (Firebase Console)

### Key Metrics to Monitor

1. **Function Executions**
   - Navigate to: Functions → pulse → Metrics
   - Expected: ~60 executions/hour (once per minute)

2. **Function Errors**
   - Same dashboard
   - Expected: 0 errors (or minimal if API rate limits hit)

3. **Firestore Writes**
   - Navigate to: Firestore → Usage
   - Expected: ~60 writes/hour to `systemStatus/market_regime`

4. **Firestore Data**
   - Navigate to: Firestore → Data → systemStatus → market_regime
   - Fields should update every minute
   - Check `timestamp` field for freshness

## ⚠️ Troubleshooting

### Issue: GEX always returns 0.00

**Symptoms**: `net_gex` is always "0.00", `option_count` is 0

**Possible Causes**:
1. No Alpaca API keys configured
2. Alpaca account doesn't have options data access
3. Market is closed (limited options data)
4. API rate limiting

**Solutions**:
```bash
# Check logs for specific error
gcloud functions logs read pulse --limit=100 | grep -i "error"

# Verify Alpaca keys are configured
gcloud firestore documents list --collection-path=users

# Test API access manually
python3 functions/example_gex_usage.py
```

### Issue: Pulse function not executing

**Symptoms**: No logs, Firestore data not updating

**Possible Causes**:
1. Function not deployed
2. Scheduler not enabled
3. Function deployment error

**Solutions**:
```bash
# Check function exists
gcloud functions list | grep pulse

# Re-deploy function
firebase deploy --only functions:pulse

# Check scheduler status
gcloud scheduler jobs list
```

### Issue: "No Alpaca API client available for GEX calculation"

**Symptoms**: Warning in logs, GEX not calculated

**Cause**: No users with valid Alpaca keys in Firestore

**Solution**:
```bash
# Add Alpaca keys for at least one user
# Use Firebase Console or:
gcloud firestore documents set \
  users/{userId}/secrets/alpaca \
  --data='{"key_id":"YOUR_KEY","secret_key":"YOUR_SECRET","base_url":"https://paper-api.alpaca.markets"}'
```

### Issue: High latency (>10 seconds per calculation)

**Symptoms**: Pulse function timeout warnings

**Cause**: Large option chains with many strikes

**Solutions**:
- This is expected for SPY/QQQ with 0DTE and 1DTE options
- Increase function timeout if needed:
  ```javascript
  // In functions/main.js or index.js
  exports.pulse = functions
    .runWith({ timeoutSeconds: 120 }) // Increase from default
    .pubsub.schedule('* * * * *')
    .onRun(async (context) => { ... });
  ```

## 🎉 Success Criteria

Your deployment is successful when:

- [ ] Pulse function executes every minute
- [ ] Firestore `systemStatus/market_regime` updates every minute
- [ ] `spy.net_gex` and `qqq.net_gex` have non-zero values (during market hours)
- [ ] `market_volatility_bias` is "Bullish", "Bearish", or "Neutral"
- [ ] No errors in function logs (or minimal transient errors)
- [ ] GammaScalper can fetch GEX from Firestore
- [ ] Example script runs successfully

## 📞 Support

If you encounter issues:

1. Check logs: `gcloud functions logs read pulse --limit=100`
2. Review documentation: `functions/GEX_ENGINE_QUICKSTART.md`
3. Run example script: `python3 functions/example_gex_usage.py`
4. Run tests: `pytest functions/test_gex_engine.py -v`

## 🔄 Rollback Plan

If GEX engine causes issues:

```bash
# Option 1: Disable GEX calculation
# Comment out the GEX calculation in functions/main.py:
# Lines ~280-295 in pulse function

# Option 2: Revert to previous version
git revert <commit-hash>
firebase deploy --only functions:pulse
```

## 📈 Next Steps After Deployment

1. **Monitor for 24 hours** to ensure stable operation
2. **Analyze GEX patterns** during different market conditions
3. **Backtest strategies** with GEX-aware logic
4. **Add frontend visualization** of GEX data
5. **Create alerts** for extreme GEX levels
6. **Expand to more symbols** (IWM, DIA, etc.)

---

**Deployment Date**: _________________

**Deployed By**: _________________

**Verification Status**: _________________

**Notes**: _________________________________________________
