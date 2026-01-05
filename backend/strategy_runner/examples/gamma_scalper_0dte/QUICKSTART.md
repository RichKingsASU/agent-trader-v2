# 0DTE Gamma Scalper - Quick Start Guide

## 🚀 Quick Test (30 seconds)

```bash
cd /workspace
python3 backend/strategy_runner/examples/gamma_scalper_0dte/smoke_test.py
```

Expected output: ✅ All smoke tests passed!

## 📋 What's Implemented

| Feature | Status | Location |
|---------|--------|----------|
| Net Portfolio Delta Calculation | ✅ | `_get_net_portfolio_delta()` |
| Hedging Logic (0.15 threshold) | ✅ | `_should_hedge()` |
| GEX-Based Adaptive Thresholds | ✅ | `_get_hedging_threshold()` |
| Time-Based Exit (3:45 PM ET) | ✅ | `_is_market_close_time()` |
| Decimal Precision | ✅ | All calculations |
| Firestore Integration | ✅ | `_fetch_gex_from_firestore()` |

## 🎯 Key Parameters

```python
HEDGING_THRESHOLD = 0.15              # Standard threshold
HEDGING_THRESHOLD_NEGATIVE_GEX = 0.10 # Tighter when GEX < 0
EXIT_TIME_ET = time(15, 45, 0)        # 3:45 PM Eastern
```

## 📊 Example: How It Works

### Scenario: Long Call Position

```
Position:
  - 10 SPY calls @ 0.65 delta each
  - Net Delta = 10 × 0.65 = 6.5

Hedging Decision:
  - abs(6.5) > 0.15? ✅ Yes → Trigger hedge
  - Hedge Qty = -6.5 → SELL 7 shares of SPY
  - New Net Delta ≈ 0
```

### Scenario: Negative GEX Environment

```
GEX = -15000 (market short gamma)
Position Net Delta = 0.12

Standard threshold (0.15): No hedge ❌
Negative GEX threshold (0.10): Hedge ✅

Result: SELL 1 share of SPY
```

### Scenario: Market Close

```
Current Time: 3:45 PM ET
Open Positions:
  - 10 SPY calls
  - 5 SPY puts

Action: Exit ALL positions
  - SELL 10 call contracts
  - BUY 5 put contracts
  - Portfolio cleared ✅
```

## 🧪 Full Test Suite

```bash
# Smoke test (quick)
python3 backend/strategy_runner/examples/gamma_scalper_0dte/smoke_test.py

# Integration test (detailed)
python3 backend/strategy_runner/examples/gamma_scalper_0dte/test_strategy.py

# Unit tests (requires pytest)
pytest tests/test_gamma_scalper_strategy.py -v
```

## 🔧 Configuration

### Environment Variables

```bash
# Optional: Override GEX value
export GEX_VALUE=-15000.0

# Production: Firestore credentials
export FIREBASE_PROJECT_ID=your-project-id
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

### Firestore Data Structure

```
Collection: market_regime
Document: SPX_GEX

{
  "gex_value": -15000.0,
  "last_update": Timestamp,
  "symbol": "SPX"
}
```

## 📝 Input/Output

### Input: Market Event

```json
{
  "protocol": "v1",
  "type": "market_event",
  "event_id": "evt_001",
  "ts": "2025-12-30T14:00:00Z",
  "symbol": "SPY251230C00500000",
  "source": "alpaca",
  "payload": {
    "delta": 0.65,
    "quantity": 10,
    "price": 2.50,
    "underlying_price": 495.50
  }
}
```

### Output: Order Intent

```json
{
  "protocol": "v1",
  "type": "order_intent",
  "intent_id": "hedge_SPY_abc123",
  "event_id": "evt_001",
  "ts": "2025-12-30T14:00:00Z",
  "symbol": "SPY",
  "side": "sell",
  "qty": 7.0,
  "order_type": "market",
  "client_tag": "0dte_gamma_scalper_hedge",
  "metadata": {
    "reason": "delta_hedge",
    "net_delta_before": "6.50",
    "hedge_qty": "-7",
    "underlying_price": "495.50",
    "hedging_threshold": "0.15",
    "gex_value": null,
    "strategy": "0dte_gamma_scalper"
  }
}
```

## 📂 Files

```
gamma_scalper_0dte/
├── strategy.py              ← Main implementation
├── README.md                ← Full documentation
├── QUICKSTART.md            ← This file
├── IMPLEMENTATION_SUMMARY.md ← Technical details
├── events.ndjson            ← Sample test data
├── test_strategy.py         ← Integration tests
├── smoke_test.py            ← Quick verification
└── config.example.env       ← Configuration template
```

## ⚠️ Safety Features

1. **Decimal Precision**: No floating-point errors
2. **Time-Based Exit**: All positions closed before market close
3. **Rate Limiting**: Max 1 hedge per 60 seconds
4. **Validation**: Checks underlying price before hedging
5. **Adaptive**: Tighter thresholds in volatile markets (negative GEX)

## 🎓 Learn More

- Full documentation: `README.md`
- Implementation details: `IMPLEMENTATION_SUMMARY.md`
- Protocol reference: `/workspace/backend/strategy_runner/protocol.py`
- Firestore schema: `/workspace/FIRESTORE_DATA_MODEL.md`

## ✅ Verification

Run this to verify everything works:

```bash
cd /workspace
python3 backend/strategy_runner/examples/gamma_scalper_0dte/smoke_test.py && \
echo "" && \
echo "✅ Strategy is ready to use!"
```

## 🚀 Next Steps

1. ✅ Run smoke test
2. ✅ Review README.md
3. ⏳ Test with paper trading
4. ⏳ Configure Firestore GEX data source
5. ⏳ Deploy to production

---

**Status**: ✅ Complete and Tested
**Version**: 1.0
**Date**: December 30, 2025
