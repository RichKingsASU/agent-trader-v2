# Multi-Strategy Architecture - Technical Design

**Last Updated**: December 30, 2025  
**Status**: Production Ready

---

## 🏗️ System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React/TypeScript)                  │
│                                                                       │
│  ┌────────────────┐    ┌────────────────┐    ┌──────────────────┐  │
│  │  Signal Widget │    │ Shadow P&L UI  │    │ Strategy Manager │  │
│  └────────┬───────┘    └────────┬───────┘    └────────┬─────────┘  │
│           │                     │                      │             │
└───────────┼─────────────────────┼──────────────────────┼─────────────┘
            │                     │                      │
            ▼                     ▼                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CLOUD FUNCTIONS (Python/Firebase)                 │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  generate_trading_signal()  [HTTPS Callable]                 │   │
│  │  ─────────────────────────────────────────────────────────   │   │
│  │  1. Risk Check (trading_enabled flag)                        │   │
│  │  2. Get Account Snapshot (Alpaca API)                        │   │
│  │  3. Fetch Market Data (Real-time prices)                     │   │
│  │  4. Evaluate All Active Strategies ───────┐                  │   │
│  │  5. Select Best Signal (max confidence)   │                  │   │
│  │  6. Execute Shadow Trade                  │                  │   │
│  │  7. Persist to tradingSignals            │                  │   │
│  └──────────────────────────────────────────┼──────────────────┘   │
│                                              │                       │
│  ┌──────────────────────────────────────────▼──────────────────┐   │
│  │  STRATEGY EVALUATION ENGINE                                  │   │
│  │  ───────────────────────────────────────────────────────     │   │
│  │                                                               │   │
│  │  ┌─────────────────────────────────────────────────────┐    │   │
│  │  │  BaseStrategy (ABC)                                  │    │   │
│  │  │  ───────────────────────────────────────────────     │    │   │
│  │  │  + name: str                                         │    │   │
│  │  │  + config: dict                                      │    │   │
│  │  │  + evaluate(market_data, account_snapshot) -> dict  │    │   │
│  │  └─────────────────────────────────────────────────────┘    │   │
│  │                        △                                     │   │
│  │                        │ inherits                             │   │
│  │         ┌──────────────┼──────────────┐                      │   │
│  │         │              │              │                      │   │
│  │  ┌──────▼──────┐ ┌────▼─────┐ ┌──────▼──────┐               │   │
│  │  │  Momentum   │ │   Mean   │ │   Options   │  [Future]     │   │
│  │  │  Strategy   │ │ Reversion│ │    GEX      │               │   │
│  │  └─────────────┘ └──────────┘ └─────────────┘               │   │
│  │                                                               │   │
│  │  Loop through all active strategies:                         │   │
│  │    for strategy in active_strategies:                        │   │
│  │      signal = await strategy.evaluate(...)                   │   │
│  │      signals.append(signal)                                  │   │
│  │                                                               │   │
│  │  best = max(signals, key=lambda s: s['confidence'])          │   │
│  └───────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  _execute_shadow_trade()                                      │   │
│  │  ───────────────────────────────────────────────────────      │   │
│  │  1. Calculate position size (Decimal math)                   │   │
│  │  2. Create shadowTradeHistory document                       │   │
│  │  3. Store entry_price as STRING (fintech precision)          │   │
│  │  4. Set status = "OPEN", unrealized_pnl = "0.00"             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  pulse()  [Scheduled: Every 60 seconds]                       │   │
│  │  ───────────────────────────────────────────────────────      │   │
│  │  1. Sync Alpaca account to Firestore                         │   │
│  │  2. Update HWM and calculate drawdown                        │   │
│  │  3. Update trading_enabled flag                              │   │
│  │  4. Call _update_shadow_trade_pnl() ──────────┐              │   │
│  └───────────────────────────────────────────────┼──────────────┘   │
│                                                   │                  │
│  ┌────────────────────────────────────────────────▼─────────────┐   │
│  │  _update_shadow_trade_pnl()                                   │   │
│  │  ────────────────────────────────────────────────────────     │   │
│  │  1. Query all OPEN shadow trades                             │   │
│  │  2. For each trade:                                          │   │
│  │     - Fetch current market price (Alpaca)                    │   │
│  │     - Calculate P&L with Decimal:                            │   │
│  │       BUY:  pnl = (current - entry) * qty                    │   │
│  │       SELL: pnl = (entry - current) * qty                    │   │
│  │     - Update unrealized_pnl, current_price (as strings)      │   │
│  │  3. Update last_pnl_update timestamp                         │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                       │
└───────────────────────────────────────────────────────┬───────────────┘
                                                        │
                                                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         FIRESTORE DATABASE                           │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  shadowTradeHistory/  [Shadow Mode Paper Trades]            │    │
│  │  ────────────────────────────────────────────────────────    │    │
│  │  {trade_id}: {                                               │    │
│  │    symbol: "SPY",                                            │    │
│  │    action: "BUY",                                            │    │
│  │    side: "BUY",                                              │    │
│  │    quantity: 10,                                             │    │
│  │    entry_price: "450.25",      // STRING ✅                  │    │
│  │    allocation: 0.15,                                         │    │
│  │    reasoning: "Strong momentum",                             │    │
│  │    metadata: {...},                                          │    │
│  │    status: "OPEN",                                           │    │
│  │    unrealized_pnl: "-15.50",   // STRING ✅                  │    │
│  │    current_price: "448.75",    // STRING ✅                  │    │
│  │    created_at: Timestamp,                                    │    │
│  │    last_pnl_update: Timestamp                                │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  tradingSignals/  [Signal Audit Trail]                      │    │
│  │  ────────────────────────────────────────────────────────    │    │
│  │  {signal_id}: {                                              │    │
│  │    action: "BUY",                                            │    │
│  │    ticker: "SPY",                                            │    │
│  │    allocation: 0.15,                                         │    │
│  │    reasoning: "...",                                         │    │
│  │    metadata: {...},                                          │    │
│  │    timestamp: Timestamp,                                     │    │
│  │    account_snapshot: {...},                                  │    │
│  │    market_data: {...},                                       │    │
│  │    execution: {shadow_trade details}                         │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  systemStatus/risk_management  [Risk Kill-Switch]           │    │
│  │  ────────────────────────────────────────────────────────    │    │
│  │  {                                                           │    │
│  │    trading_enabled: true/false,                              │    │
│  │    high_water_mark: "10500.00",                              │    │
│  │    drawdown_percent: 0.0325,                                 │    │
│  │    last_update: Timestamp                                    │    │
│  │  }                                                           │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         ALPACA BROKER API                            │
│                                                                       │
│  • Account Snapshot (equity, buying_power, cash)                    │
│  • Market Data (latest trades, quotes)                              │
│  • Order Execution (future: live trading)                           │
│  • Position Management                                               │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Data Flow Sequences

### Sequence 1: Signal Generation & Shadow Trade Execution

```
User clicks "Generate Signal" in Frontend
    │
    ├─→ Call generate_trading_signal() Cloud Function
    │
    ├─→ Check trading_enabled flag in Firestore
    │   └─→ If false: Return HOLD signal, exit
    │
    ├─→ Get Alpaca account snapshot
    │   └─→ equity, buying_power, cash (as strings)
    │
    ├─→ Fetch market data for symbols
    │   └─→ Current prices, timestamps
    │
    ├─→ Evaluate all active strategies
    │   ├─→ Strategy 1: await evaluate(market_data, account)
    │   ├─→ Strategy 2: await evaluate(market_data, account)
    │   └─→ Strategy N: await evaluate(market_data, account)
    │
    ├─→ Select best signal (highest confidence)
    │
    ├─→ If action != HOLD:
    │   ├─→ Calculate position size (Decimal math)
    │   │   └─→ notional = buying_power * allocation
    │   │       quantity = int(notional / price)
    │   │
    │   └─→ Call _execute_shadow_trade()
    │       ├─→ Create shadowTradeHistory document
    │       │   └─→ entry_price as STRING ✅
    │       │       unrealized_pnl = "0.00"
    │       │       status = "OPEN"
    │       │
    │       └─→ Return trade_id
    │
    ├─→ Persist signal to tradingSignals collection
    │
    └─→ Return result to frontend
        └─→ Display signal + execution details
```

### Sequence 2: Periodic P&L Updates (Every 60 seconds)

```
Cloud Scheduler triggers pulse() function
    │
    ├─→ Sync Alpaca account to Firestore
    │
    ├─→ Update risk management (HWM, drawdown)
    │
    └─→ Call _update_shadow_trade_pnl()
        │
        ├─→ Query shadowTradeHistory where status == "OPEN"
        │
        ├─→ For each OPEN trade:
        │   │
        │   ├─→ Get entry_price (string → Decimal)
        │   │
        │   ├─→ Fetch current market price from Alpaca
        │   │   └─→ Convert to Decimal
        │   │
        │   ├─→ Calculate unrealized P&L:
        │   │   ├─→ If BUY:  pnl = (current - entry) * qty
        │   │   └─→ If SELL: pnl = (entry - current) * qty
        │   │
        │   └─→ Update Firestore document:
        │       └─→ unrealized_pnl: str(pnl)  ✅ STRING
        │           current_price: str(current)  ✅ STRING
        │           last_pnl_update: SERVER_TIMESTAMP
        │
        └─→ Log summary (updates_count, errors_count)
```

---

## 📐 Class Hierarchy

```
┌─────────────────────────────────────────────────────────┐
│  ABC (Python standard library)                          │
│  ────────────────────────────────────────────────────   │
│  Abstract Base Class metaclass                          │
└─────────────────────────────────────────────────────────┘
                        △
                        │ inherits
                        │
┌─────────────────────────────────────────────────────────┐
│  BaseStrategy (functions/strategies/base.py)            │
│  ────────────────────────────────────────────────────   │
│  + name: str                                            │
│  + config: dict                                         │
│  + __init__(name, config)                               │
│  + evaluate(market_data, account_snapshot) [abstract]   │
│  ────────────────────────────────────────────────────   │
│  ⚠️  CANNOT BE INSTANTIATED DIRECTLY                    │
│  ✅  ENFORCED BY ABC METACLASS                          │
└─────────────────────────────────────────────────────────┘
                        △
                        │ inherits
        ┌───────────────┼───────────────┐
        │               │               │
┌───────▼──────┐ ┌──────▼──────┐ ┌─────▼──────┐
│  Momentum    │ │    Mean     │ │  Options   │
│  Strategy    │ │  Reversion  │ │    GEX     │
│              │ │   Strategy  │ │  Strategy  │
│  [FUTURE]    │ │   [FUTURE]  │ │  [FUTURE]  │
└──────────────┘ └─────────────┘ └────────────┘

Each concrete strategy MUST implement:
  ✅ evaluate(market_data, account_snapshot) -> dict

Signal format:
  {
    'action': 'BUY' | 'SELL' | 'HOLD',
    'allocation': 0.0 - 1.0,
    'ticker': str,
    'reasoning': str,
    'metadata': dict
  }
```

---

## 💾 Data Models

### Shadow Trade Document

```python
{
  # Identity
  "symbol": str,              # "SPY", "AAPL"
  "action": str,              # "BUY", "SELL"
  "side": str,                # "BUY", "SELL"
  
  # Position
  "quantity": int,            # Number of shares
  "entry_price": str,         # "450.25" ✅ STRING
  "allocation": float,        # 0.15 (15% of buying power)
  
  # Strategy Context
  "reasoning": str,           # "Strong momentum signal"
  "metadata": {               # Strategy-specific data
    "indicator_value": float,
    "confidence": float,
    "gex_level": float,      # Example for options strategy
  },
  
  # Status
  "status": str,              # "OPEN" | "CLOSED"
  
  # P&L Tracking
  "unrealized_pnl": str,      # "-15.50" ✅ STRING
  "current_price": str,       # "448.75" ✅ STRING
  
  # Timestamps
  "created_at": Timestamp,
  "last_pnl_update": Timestamp,
}
```

### Trading Signal Document

```python
{
  # Signal
  "action": str,              # "BUY", "SELL", "HOLD"
  "ticker": str,              # "SPY"
  "allocation": float,        # 0.15
  
  # Context
  "reasoning": str,
  "metadata": dict,
  "timestamp": Timestamp,
  
  # Account State
  "account_snapshot": {
    "equity": str,            # "10500.00" ✅ STRING
    "buying_power": str,      # "42000.00" ✅ STRING
    "cash": str,              # "5250.00" ✅ STRING
    "portfolio_value": str,   # "10500.00" ✅ STRING
  },
  
  # Market State
  "market_data": {
    "SPY": {
      "price": str,           # "450.25" ✅ STRING
      "timestamp": str,
    }
  },
  
  # Execution
  "execution": {              # Result of _execute_shadow_trade()
    "success": bool,
    "trade_id": str,
    "shadow_trade": dict,
  }
}
```

---

## 🔢 Fintech Precision Pattern

### Problem: Floating Point Errors

```python
# ❌ WRONG - Floating point arithmetic loses precision
buying_power = 10000.00
allocation = 0.15
price = 450.25

notional = buying_power * allocation  # 1500.0000000000002 (error!)
quantity = int(notional / price)      # Could be off by 1 share
```

### Solution: Decimal Arithmetic

```python
# ✅ CORRECT - Decimal maintains exact precision
from decimal import Decimal

buying_power = Decimal("10000.00")
allocation = Decimal("0.15")
price = Decimal("450.25")

notional = buying_power * allocation  # Decimal("1500.00") ✅
quantity = int(notional / price)      # Correct calculation

# Store as string in Firestore
firestore_doc = {
    "notional": str(notional),        # "1500.00"
    "price": str(price),              # "450.25"
}
```

### Implementation Pattern

```python
def calculate_pnl_with_precision(
    entry_price_str: str,
    current_price_str: str,
    quantity: int,
    side: str,
) -> str:
    """Calculate P&L with fintech precision."""
    # Step 1: Convert strings to Decimal
    entry = Decimal(entry_price_str)
    current = Decimal(current_price_str)
    qty = Decimal(str(quantity))
    
    # Step 2: Perform arithmetic with Decimal
    if side == "BUY":
        pnl = (current - entry) * qty
    else:  # SELL
        pnl = (entry - current) * qty
    
    # Step 3: Return as string for storage
    return str(pnl)  # "15.50" or "-15.50"
```

**Key Rules**:
1. ✅ Always use `Decimal(str(value))` for conversion
2. ✅ Perform all arithmetic with Decimal types
3. ✅ Store results as strings in Firestore
4. ❌ Never use `float()` for financial calculations
5. ❌ Never perform arithmetic on string types directly

---

## 🧪 Testing Strategy

### Unit Tests (`tests/test_base_strategy.py`)

1. **ABC Enforcement**
   - Cannot instantiate `BaseStrategy` directly
   - Concrete strategies must implement `evaluate()`
   - Proper TypeError exceptions raised

2. **Decimal Precision**
   - Position sizing calculations
   - P&L calculations
   - No floating-point errors

3. **Signal Format**
   - Standardized return structure
   - All required fields present
   - Correct data types

### Integration Tests (Future)

1. **End-to-End Signal Flow**
   - Generate signal → Shadow trade → P&L update
   - Multi-strategy evaluation
   - Risk management integration

2. **Shadow Trade Lifecycle**
   - Create OPEN trade
   - Update P&L every minute
   - Close trade and calculate realized P&L

3. **Error Handling**
   - Missing market data
   - Alpaca API failures
   - Invalid strategy configurations

---

## 🚀 Production Roadmap

### Phase 1: Foundation ✅ COMPLETE
- [x] BaseStrategy ABC
- [x] Directory structure
- [x] Shadow mode execution
- [x] P&L tracking
- [x] Decimal precision

### Phase 2: First Concrete Strategy (Next)
- [ ] Implement MomentumStrategy
- [ ] Configure strategy parameters
- [ ] Deploy and test in shadow mode
- [ ] Monitor performance metrics

### Phase 3: Multi-Strategy Support
- [ ] Strategy registry system
- [ ] Configuration management UI
- [ ] Strategy enable/disable toggles
- [ ] Performance comparison dashboard

### Phase 4: Live Trading
- [ ] Shadow → Live mode toggle
- [ ] Pre-flight validation
- [ ] Gradual rollout (1% → 100%)
- [ ] Real-time monitoring and alerts

---

## 📊 Monitoring & Observability

### Key Metrics

1. **Signal Generation**
   - Latency (target: < 2s)
   - Success rate (target: > 99%)
   - Strategy evaluation time per strategy

2. **Shadow Trades**
   - Trades created per day
   - Average P&L per trade
   - Win rate (profitable trades / total)
   - Maximum drawdown

3. **P&L Updates**
   - Update success rate (target: 100%)
   - Stale trades (last_pnl_update > 5 min)
   - Update latency

4. **System Health**
   - pulse() heartbeat consistency
   - Error rates by function
   - Firestore quota usage

### Logging Pattern

```python
# Strategic logging throughout the system
logger.info(f"Shadow trade recorded: {action} {quantity} {symbol} @ {entry_price}")
logger.debug(f"Updated P&L for {symbol}: entry={entry}, current={current}, pnl={pnl}")
logger.warning(f"Failed to get price for {symbol}: {error}")
logger.error(f"Error updating shadow trade {trade_id}: {error}")
```

---

## 🔒 Security Considerations

1. **Firestore Rules**
   - Users can only read/write their own trades
   - Server-side validation of all inputs
   - Rate limiting on signal generation

2. **API Keys**
   - Alpaca credentials in Secret Manager
   - Never exposed to frontend
   - Rotated periodically

3. **Risk Management**
   - trading_enabled kill-switch
   - Drawdown circuit breaker
   - Position size limits

---

## 📚 References

- **BaseStrategy**: `functions/strategies/base.py`
- **Main Functions**: `functions/main.py`
- **Tests**: `tests/test_base_strategy.py`
- **Documentation**: 
  - `STRATEGY_INTEGRATION_SUMMARY.md`
  - `STRATEGY_IMPLEMENTATION_CHECKLIST.md`
  - `STRATEGY_ARCHITECTURE.md` (this file)

---

**Architecture Version**: 1.0  
**Last Updated**: December 30, 2025  
**Status**: Production Ready ✅
