# Phase 4 - Trade Executor (OMS) Implementation

## Overview

Phase 4 implements a robust Order Management System (OMS) that converts AI signals into live Alpaca orders with precision math, safety checks, and comprehensive audit logging.

## Architecture Verification ✅

### ✅ Requirement 1: Float Usage
**Confirmed**: `float()` is ONLY used at the final Alpaca SDK call.

All intermediate calculations use `decimal.Decimal` for precision:
- `functions/executor.py`: All math functions use Decimal
- `functions/main.py`: Only converts to float at lines 439, 449, 450 (Alpaca API submission)

```python
# CORRECT: All math uses Decimal
notional = calculate_order_notional(buying_power, allocation_pct)  # Returns Decimal
limit_price = calculate_limit_price(current_price, side)  # Returns Decimal

# Only convert at the last moment for Alpaca API
api.submit_order(
    notional=float(notional),  # Only place float is used
    limit_price=float(limit_price)  # Only place float is used
)
```

### ✅ Requirement 2: client_order_id for Crash Recovery
**Confirmed**: `client_order_id` is unique and logged BEFORE the Alpaca API call.

Order of operations in `execute_trade`:
1. **Line 318**: Generate unique ID: `client_order_id = generate_client_order_id()`
2. **Line 319**: Log generation: `logger.info(f"Generated client_order_id: {client_order_id}")`
3. **Line 427**: Save to Firestore: `db.collection("tradeHistory").document(client_order_id).set(audit_entry)`
4. **Line 428**: Log save: `logger.info(f"Logged pending order to tradeHistory: {client_order_id}")`
5. **Line 439/452**: Submit to Alpaca (with client_order_id attached)

This ensures crash recovery: if the process crashes after logging but before Alpaca responds, we can query the tradeHistory to find pending orders.

## Implementation Details

### Backend Components

#### 1. `functions/executor.py`
Trade math utilities using `decimal.Decimal`:

**Functions:**
- `generate_client_order_id()` - Generates unique order IDs with timestamp and UUID
- `calculate_order_notional()` - Calculates order size using Decimal precision
- `calculate_limit_price()` - Generates marketable limit prices (0.5% buffer)
- `validate_order_params()` - Validates order parameters before submission
- `build_audit_log_entry()` - Creates structured audit log entries

**Key Features:**
- All calculations use `Decimal` for precision
- Supports fractional shares via notional orders
- Configurable slippage protection (default 0.5%)
- Comprehensive validation with error messages

#### 2. `functions/main.py` - `execute_trade` Function
2nd Gen Callable function with full OMS capabilities:

**Safety Checks:**
1. Parameter validation (symbol, side, allocation_pct)
2. Trading gate check (`systemStatus/trading_gate.trading_enabled`)
3. Order parameter validation (notional > $1, valid prices)

**Order Logic:**
- **Market Orders**: Use notional parameter for fractional shares
- **Limit Orders**: "Marketable Limit" with 0.5% buffer above ask (buy) or below bid (sell)
- Time-in-force: DAY orders

**Audit Logging:**
All order attempts saved to `tradeHistory` collection:
- Status progression: `pending` → `submitted` | `failed` | `rejected`
- Includes: client_order_id, symbol, side, notional, prices, timestamps
- Metadata: AI recommendation context when available

**Error Handling:**
- Validation errors: Logged and returned to client
- Trading gate disabled: Order rejected and logged
- Alpaca API errors: Caught, logged, and status updated

### Frontend Components

#### 3. `frontend/src/hooks/useTradeExecutor.ts`
Custom React hook for trade execution:

**Features:**
- Type-safe request/response interfaces
- Local validation before API call
- Loading/error/success state management
- Error handling with detailed messages

**API:**
```typescript
const { executeOrder, loading, error, lastExecution, clearError } = useTradeExecutor();

await executeOrder({
  symbol: "AAPL",
  side: "buy",
  allocation_pct: 0.1,
  order_type: "limit",
  current_price: 150.25,
  metadata: { ai_recommendation: {...} }
});
```

#### 4. `frontend/src/components/ExecutionPanel.tsx`
Comprehensive execution UI component:

**Features:**
- **AI vs Actual Comparison**: Side-by-side display of AI recommendation vs actual order
- **Order Configuration**: Symbol, side, allocation %, order type
- **Real-time Calculation**: Shows calculated order size based on buying power
- **Confirmation Dialog**: Two-step confirmation before execution
- **Status Feedback**: Success/error alerts with detailed messages
- **Visual Design**: Modern UI with color-coded buy/sell indicators

**Props:**
```typescript
interface ExecutionPanelProps {
  aiRecommendation?: {
    action: "BUY" | "SELL" | "HOLD";
    symbol: string;
    target_allocation: number;
    confidence: number;
    reasoning: string;
  };
  accountData?: {
    buying_power: string;
    equity: string;
    cash: string;
  };
  currentPrice?: number;
  onExecutionSuccess?: (response: any) => void;
}
```

## Firestore Schema

### Collection: `systemStatus`
```typescript
// Document: trading_gate
{
  trading_enabled: boolean  // Master kill switch for all trading
}
```

### Collection: `tradeHistory`
```typescript
// Document ID: client_order_id (e.g., "AT_20231230123045_a1b2c3d4")
{
  client_order_id: string
  symbol: string
  side: "buy" | "sell"
  notional: string  // Stored as string to preserve precision
  order_type: "market" | "limit"
  limit_price?: string  // If limit order
  status: "pending" | "submitted" | "failed" | "rejected" | "validation_failed"
  error_message?: string  // If failed
  alpaca_order_id?: string  // If submitted
  alpaca_status?: string  // Alpaca's order status
  created_at: string  // ISO timestamp
  timestamp: Timestamp  // Firestore timestamp
  submitted_at?: Timestamp  // When submitted to Alpaca
  failed_at?: Timestamp  // When failed
  metadata?: object  // Additional context (e.g., AI recommendation)
  order_response?: object  // Full Alpaca response
}
```

## Order Flow

```
1. User configures order in ExecutionPanel
   ↓
2. User clicks "Confirm Execution"
   ↓
3. Confirmation dialog shown
   ↓
4. User confirms
   ↓
5. useTradeExecutor.executeOrder() called
   ↓
6. Firebase Function execute_trade triggered
   ↓
7. Safety Check: Verify trading_enabled in systemStatus/trading_gate
   ↓
8. Generate unique client_order_id
   ↓
9. Calculate order notional and limit price (Decimal math)
   ↓
10. Validate order parameters
   ↓
11. Log order to tradeHistory (status: "pending")
   ↓
12. Submit order to Alpaca API (float conversion here)
   ↓
13. Update tradeHistory (status: "submitted" or "failed")
   ↓
14. Return response to frontend
   ↓
15. Display success/error in ExecutionPanel
```

## Safety Features

### 1. Trading Gate
- Master kill switch in Firestore: `systemStatus/trading_gate.trading_enabled`
- All orders rejected when disabled
- Rejected orders logged for audit trail

### 2. Precision Math
- All calculations use `decimal.Decimal`
- Only convert to `float` at final Alpaca API call
- Prevents floating-point rounding errors

### 3. Marketable Limit Orders
- Limit orders with 0.5% slippage buffer
- BUY: Limit price = ask + 0.5%
- SELL: Limit price = bid - 0.5%
- Guarantees fills while protecting against spikes

### 4. Crash Recovery
- `client_order_id` generated and logged BEFORE Alpaca call
- If crash occurs, can query tradeHistory for pending orders
- Can reconcile with Alpaca's order status using client_order_id

### 5. Comprehensive Audit Trail
- Every order attempt logged to tradeHistory
- Status progression tracked
- Error messages preserved
- Full Alpaca response stored

### 6. Validation
- Parameter validation before processing
- Order size validation (minimum $1)
- Price validation (positive values)
- Symbol validation (non-empty string)

## Usage Example

### Frontend Integration

```typescript
import { ExecutionPanel } from "@/components/ExecutionPanel";
import { useAISignals } from "@/hooks/useAISignals";

function TradingPage() {
  const { signal } = useAISignals();
  const [accountData, setAccountData] = useState(null);

  return (
    <ExecutionPanel
      aiRecommendation={{
        action: signal.action,
        symbol: "AAPL",
        target_allocation: 0.1,
        confidence: 0.85,
        reasoning: signal.reasoning
      }}
      accountData={{
        buying_power: "10000.00",
        equity: "25000.00",
        cash: "5000.00"
      }}
      currentPrice={150.25}
      onExecutionSuccess={(response) => {
        console.log("Order executed:", response);
        // Refresh account data, positions, etc.
      }}
    />
  );
}
```

### Backend Testing

```python
# Test order execution via Firebase Functions
from firebase_functions import https_fn

# Test data
test_request = {
    "symbol": "AAPL",
    "side": "buy",
    "allocation_pct": 0.1,
    "order_type": "limit",
    "current_price": 150.25,
    "metadata": {
        "test": True,
        "ai_recommendation": {
            "action": "BUY",
            "confidence": 0.85
        }
    }
}

# Execute
response = execute_trade(https_fn.CallableRequest(data=test_request))
print(response)
```

## Testing Checklist

- [ ] Enable trading gate: Set `systemStatus/trading_gate.trading_enabled = true`
- [ ] Test with trading gate disabled (should reject)
- [ ] Test market order execution
- [ ] Test limit order execution
- [ ] Verify Decimal precision (no rounding errors)
- [ ] Verify client_order_id uniqueness
- [ ] Verify audit log entries in tradeHistory
- [ ] Test with invalid parameters
- [ ] Test with insufficient buying power
- [ ] Test crash recovery (manual process restart)
- [ ] Verify Alpaca order submission
- [ ] Verify frontend ExecutionPanel display
- [ ] Test confirmation dialog workflow

## Dependencies

### Backend
```txt
alpaca-trade-api>=3.0.0
firebase-admin>=6.0.0
firebase-functions>=0.4.0
```

### Frontend
```json
{
  "firebase": "^10.0.0",
  "@/components/ui": "shadcn/ui components"
}
```

## Environment Variables

```bash
# Alpaca credentials (required)
APCA_API_KEY_ID=your_key_id
APCA_API_SECRET_KEY=your_secret_key
APCA_API_BASE_URL=https://paper-api.alpaca.markets  # For paper trading

# Or alternative names
APCA_API_KEY_ID=your_key_id
APCA_API_SECRET_KEY=your_secret_key
APCA_API_BASE_URL=https://paper-api.alpaca.markets
```

## Deployment

### Firebase Functions Deployment

```bash
# Deploy all functions
firebase deploy --only functions

# Deploy only execute_trade
firebase deploy --only functions:execute_trade

# Set secrets (if using Secret Manager)
firebase functions:secrets:set APCA_API_KEY_ID
firebase functions:secrets:set APCA_API_SECRET_KEY
```

### Frontend Build

```bash
cd frontend
npm run build
firebase deploy --only hosting
```

## Monitoring

### Key Metrics to Track

1. **Order Success Rate**
   - Query: `tradeHistory` where `status = "submitted"`
   - Target: > 95%

2. **Order Rejection Rate**
   - Query: `tradeHistory` where `status = "rejected"`
   - Alert: If > 5%

3. **Average Execution Time**
   - Measure: Time from `created_at` to `submitted_at`
   - Target: < 2 seconds

4. **Precision Errors**
   - Monitor: Notional amount vs executed amount
   - Alert: If difference > 0.1%

5. **Trading Gate Status**
   - Monitor: `systemStatus/trading_gate.trading_enabled`
   - Alert: When changed

### Log Queries

```bash
# View recent executions
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=execute_trade" --limit 50

# View errors
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=execute_trade AND severity>=ERROR" --limit 50

# View trading gate checks
gcloud logging read "jsonPayload.message=~'Trading gate'" --limit 20
```

## Next Steps

1. **Phase 5**: Position Management & PnL Tracking
2. **Phase 6**: Risk Management & Circuit Breakers
3. **Phase 7**: Performance Attribution & Analytics

## References

- [Alpaca API Documentation](https://alpaca.markets/docs/api-documentation/)
- [Firebase Functions v2](https://firebase.google.com/docs/functions/callable)
- [Decimal Precision in Python](https://docs.python.org/3/library/decimal.html)
- [AgentTrader Architecture](./ARCHITECTURE_VERIFICATION_CHECKLIST.md)
