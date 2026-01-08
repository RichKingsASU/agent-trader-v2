# Phase 4: Trade Executor - Quick Start Guide

## 🚀 What Was Built

Phase 4 implements a production-ready Order Management System (OMS) that converts AI signals into live Alpaca orders.

### Backend (Python - Firebase Functions)
- ✅ `functions/executor.py` - Trade math utilities with Decimal precision
- ✅ `functions/main.py` - `execute_trade` Cloud Function with safety checks

### Frontend (TypeScript - React)
- ✅ `src/hooks/useTradeExecutor.ts` - Trade execution hook
- ✅ `src/components/ExecutionPanel.tsx` - Execution UI component

## 🔐 Architecture Compliance

### ✅ Requirement 1: Decimal Precision
- All intermediate calculations use `decimal.Decimal`
- `float()` ONLY used at final Alpaca SDK call (lines 439, 449, 450 in main.py)
- No floating-point rounding errors

### ✅ Requirement 2: Crash Recovery
- `client_order_id` generated FIRST (line 318)
- Logged to Firestore BEFORE Alpaca call (line 427)
- Can recover from crashes by querying `tradeHistory` collection

## 📋 Setup Instructions

### 1. Initialize Trading Gate (Required!)

```bash
# Using Firebase Console or gcloud
firebase firestore:set systemStatus/trading_gate '{"trading_enabled": false}'

# Or via Firebase Console:
# Collection: systemStatus
# Document: trading_gate
# Field: trading_enabled = false (boolean)
```

**⚠️ IMPORTANT**: Start with `trading_enabled: false` until you're ready to go live!

### 2. Deploy Backend

```bash
# From project root
cd functions
pip install -r requirements.txt

# Deploy to Firebase
firebase deploy --only functions:execute_trade

# Or deploy all functions
firebase deploy --only functions
```

### 3. Set Alpaca Credentials

#### Option A: Environment Variables (Local Testing)
```bash
export APCA_API_KEY_ID=your_key_id
export APCA_API_SECRET_KEY=your_secret_key
export APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

#### Option B: Firebase Secret Manager (Production)
```bash
# Set secrets
firebase functions:secrets:set APCA_API_KEY_ID
firebase functions:secrets:set APCA_API_SECRET_KEY

# Update function config in main.py (already done):
@https_fn.on_call(secrets=["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"])
```

### 4. Build & Deploy Frontend

```bash
cd frontend
npm install
npm run build
firebase deploy --only hosting
```

## 🧪 Testing

### Test 1: Trading Gate Disabled (Should Reject)

```javascript
// In browser console or test script
const functions = getFunctions();
const executeTrade = httpsCallable(functions, 'execute_trade');

const result = await executeTrade({
  symbol: "AAPL",
  side: "buy",
  allocation_pct: 0.01,  // 1% of buying power
  order_type: "limit",
  current_price: 150.00
});

// Expected: Error "Trading is currently disabled"
```

### Test 2: Enable Trading Gate & Execute

```bash
# Enable trading
firebase firestore:set systemStatus/trading_gate '{"trading_enabled": true}'
```

```javascript
// Try again
const result = await executeTrade({
  symbol: "AAPL",
  side: "buy",
  allocation_pct: 0.01,
  order_type: "limit",
  current_price: 150.00
});

// Expected: Success response with client_order_id and alpaca_order_id
console.log(result.data);
```

### Test 3: Verify Audit Trail

```javascript
// Check tradeHistory collection
const db = getFirestore();
const tradeHistoryRef = collection(db, 'tradeHistory');
const recentTrades = await getDocs(
  query(tradeHistoryRef, orderBy('timestamp', 'desc'), limit(10))
);

recentTrades.forEach(doc => {
  console.log(doc.id, doc.data());
});

// Expected: See your order with status "submitted" or "failed"
```

## 🎨 Frontend Integration

### Basic Usage

```typescript
import { ExecutionPanel } from "@/components/ExecutionPanel";

function TradingPage() {
  return (
    <ExecutionPanel
      aiRecommendation={{
        action: "BUY",
        symbol: "AAPL",
        target_allocation: 0.1,
        confidence: 0.85,
        reasoning: "Strong momentum and positive earnings"
      }}
      accountData={{
        buying_power: "10000.00",
        equity: "25000.00",
        cash: "5000.00"
      }}
      currentPrice={150.25}
      onExecutionSuccess={(response) => {
        console.log("Order executed:", response);
        // Refresh data, show notification, etc.
      }}
    />
  );
}
```

### Advanced: Integrate with useAISignals

```typescript
import { ExecutionPanel } from "@/components/ExecutionPanel";
import { useAISignals } from "@/hooks/useAISignals";
import { useEffect, useState } from "react";
import { getFirestore, doc, onSnapshot } from "firebase/firestore";

function TradingDashboard() {
  const { signal } = useAISignals();
  const [accountData, setAccountData] = useState(null);
  const [currentPrice, setCurrentPrice] = useState(null);

  // Subscribe to account snapshot
  useEffect(() => {
    const db = getFirestore();
    const accountRef = doc(db, "alpacaAccounts", "snapshot");
    
    const unsubscribe = onSnapshot(accountRef, (snap) => {
      if (snap.exists()) {
        const data = snap.data();
        setAccountData({
          buying_power: data.buying_power || "0",
          equity: data.equity || "0",
          cash: data.cash || "0"
        });
      }
    });

    return () => unsubscribe();
  }, []);

  // Fetch current price (implement your price feed)
  useEffect(() => {
    if (signal?.symbol) {
      fetchCurrentPrice(signal.symbol).then(setCurrentPrice);
    }
  }, [signal]);

  return (
    <div className="space-y-4">
      <h1>Trading Dashboard</h1>
      
      <ExecutionPanel
        aiRecommendation={signal ? {
          action: signal.action,
          symbol: signal.symbol || "AAPL",
          target_allocation: signal.target_allocation || 0.1,
          confidence: signal.confidence || 0.5,
          reasoning: signal.reasoning || ""
        } : undefined}
        accountData={accountData}
        currentPrice={currentPrice}
        onExecutionSuccess={(response) => {
          console.log("Trade executed:", response);
          // Show success notification
          toast.success(`Order ${response.client_order_id} submitted!`);
        }}
      />
    </div>
  );
}
```

## 🔍 Monitoring

### View Recent Orders

```bash
# Firestore Console
# Navigate to: tradeHistory collection
# Sort by: timestamp (descending)
```

### Check Function Logs

```bash
# View logs
firebase functions:log --only execute_trade

# Or via gcloud
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=execute_trade" --limit 50
```

### Monitor Trading Gate

```javascript
// Real-time trading gate status
const db = getFirestore();
const gateRef = doc(db, "systemStatus", "trading_gate");

onSnapshot(gateRef, (snap) => {
  if (snap.exists()) {
    const { trading_enabled } = snap.data();
    console.log("Trading gate:", trading_enabled ? "ENABLED" : "DISABLED");
  }
});
```

## 🛡️ Safety Features

### 1. Trading Gate Circuit Breaker
- Master kill switch: `systemStatus/trading_gate.trading_enabled`
- Instantly stops all trading when set to `false`
- Rejected orders are logged for audit

### 2. Marketable Limit Orders
- Default: Limit orders with 0.5% slippage protection
- BUY: Sets limit 0.5% above ask price
- SELL: Sets limit 0.5% below bid price
- Guarantees fills while protecting against flash crashes

### 3. Comprehensive Audit Trail
- Every order attempt logged to `tradeHistory`
- Status: pending → submitted | failed | rejected
- Includes: client_order_id, timestamp, error messages
- Full Alpaca response preserved

### 4. Crash Recovery
- `client_order_id` logged BEFORE Alpaca submission
- Can query pending orders after crash
- Reconcile with Alpaca using client_order_id

### 5. Decimal Precision
- All math uses `decimal.Decimal`
- No floating-point errors
- Exact cent-level precision

## 📊 Firestore Collections

### `systemStatus/trading_gate`
```json
{
  "trading_enabled": false
}
```

### `tradeHistory/{client_order_id}`
```json
{
  "client_order_id": "AT_20231230123045_a1b2c3d4",
  "symbol": "AAPL",
  "side": "buy",
  "notional": "1000.00",
  "order_type": "limit",
  "limit_price": "150.75",
  "status": "submitted",
  "alpaca_order_id": "abc123-def456",
  "alpaca_status": "accepted",
  "created_at": "2023-12-30T12:30:45.123Z",
  "timestamp": Timestamp,
  "submitted_at": Timestamp,
  "metadata": {
    "ai_recommendation": {
      "action": "BUY",
      "confidence": 0.85
    }
  }
}
```

## 🚨 Troubleshooting

### Issue: "Trading gate not configured"
**Solution**: Create the trading gate document:
```bash
firebase firestore:set systemStatus/trading_gate '{"trading_enabled": false}'
```

### Issue: "Missing Alpaca credentials"
**Solution**: Set environment variables or Firebase secrets:
```bash
firebase functions:secrets:set APCA_API_KEY_ID
firebase functions:secrets:set APCA_API_SECRET_KEY
```

### Issue: "Order validation failed: Notional too small"
**Solution**: Alpaca requires minimum $1 order. Increase allocation_pct.

### Issue: "current_price required for limit orders"
**Solution**: Pass current_price in the request or use order_type: "market"

## 📚 Next Steps

1. **Test with Paper Trading**: Use Alpaca paper trading account first
2. **Monitor Performance**: Track order success rate and execution times
3. **Add Position Management**: Track open positions and PnL
4. **Implement Risk Limits**: Max position size, daily loss limits, etc.
5. **Add Notifications**: Email/SMS alerts for order execution

## 🎯 Key Metrics to Track

- **Order Success Rate**: Target > 95%
- **Average Execution Time**: Target < 2 seconds
- **Precision Errors**: Target < 0.1% difference
- **Trading Gate Changes**: Alert on any change
- **Daily Order Volume**: Monitor for anomalies

## 📖 Documentation

- Full Implementation: `PHASE4_TRADE_EXECUTOR_IMPLEMENTATION.md`
- Architecture: `ARCHITECTURE_VERIFICATION_CHECKLIST.md`
- Alpaca API: https://alpaca.markets/docs/api-documentation/

---

**Status**: ✅ Phase 4 Complete and Production-Ready

**Last Updated**: December 30, 2025
