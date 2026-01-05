# Multi-Asset Smart Routing Implementation

## Overview

The Execution Engine has been refactored to support **Multi-Asset Smart Routing** with cost optimization. The system now intelligently routes trades across multiple asset classes (Equities, Forex, Crypto) while automatically downgrading signals when transaction costs would destroy alpha.

## Key Features

### 1. Multi-Asset Support

The system now supports trading across multiple asset classes:

- **Equities**: Traditional stocks (e.g., AAPL, TSLA, SPY)
- **Forex**: Currency pairs (e.g., EUR/USD, GBP/JPY)
- **Crypto**: Cryptocurrencies (e.g., BTC/USD, ETH/USD)
- **Options**: Equity options (existing support maintained)

### 2. Cost Optimization

Before placing any trade, the system:

1. Fetches current **bid-ask spread** from the market
2. Calculates **estimated slippage** as a percentage of asset price
3. Compares slippage against a configurable threshold (default: **0.1%**)
4. **Downgrades signal to 'WAIT'** if spread exceeds threshold
5. Logs cost analysis for audit and performance tracking

### 3. Portfolio History Persistence

All executed trades are now logged to **two locations**:

1. **Internal Ledger**: `tenants/{tenant_id}/ledger_trades/{trade_id}` (existing)
2. **User Portfolio**: `users/{uid}/portfolio/history/trades/{history_id}` (new)

The user-facing portfolio history includes:
- Asset class and symbol
- Trade details (side, quantity, price, notional)
- Cost analysis (estimated slippage, fees)
- Tax tracking fields (cost basis, tax lot method)
- Strategy and execution metadata

## Architecture Changes

### BaseStrategy (functions/strategies/base_strategy.py)

#### New Asset Classes

```python
class AssetClass(Enum):
    EQUITY = "EQUITY"
    FOREX = "FOREX"
    CRYPTO = "CRYPTO"
    OPTIONS = "OPTIONS"
```

#### Enhanced TradingSignal

```python
signal = TradingSignal(
    signal_type=SignalType.BUY,  # or WAIT if downgraded
    symbol="EUR/USD",
    asset_class=AssetClass.FOREX,
    confidence=0.85,
    reasoning="Strong momentum signal",
    estimated_slippage=0.0005,  # 0.05%
)
```

#### New Methods

- `estimate_slippage(market_data)`: Calculate slippage from bid-ask spread
- `should_downgrade_signal(market_data)`: Check if spread exceeds threshold
- `detect_asset_class(symbol)`: Auto-detect asset class from symbol format

#### Updated evaluate() Method

The `market_data` dict now includes:

```python
market_data = {
    "symbol": "BTC/USD",
    "asset_class": "CRYPTO",
    "price": 50000.0,      # mid-price or last
    "bid": 49950.0,        # current bid
    "ask": 50050.0,        # current ask
    "spread": 100.0,       # ask - bid
    "spread_pct": 0.002,   # spread / price (0.2%)
}
```

### Execution Engine (backend/execution/engine.py)

#### New Components

##### 1. MarketDataProvider

Fetches real-time quotes for slippage estimation:

```python
provider = MarketDataProvider()
quote = provider.get_quote(symbol="EUR/USD", asset_class="FOREX")
# Returns: {bid, ask, spread, spread_pct, mid_price}
```

##### 2. SmartRouter

Analyzes order intents and decides whether to execute or downgrade:

```python
router = SmartRouter(max_spread_pct=0.001)  # 0.1% threshold
decision = router.analyze_intent(intent=intent)

if decision.should_execute:
    # Proceed with execution
else:
    # Signal downgraded to WAIT
    print(f"Downgraded: {decision.reason}")
```

##### 3. Enhanced OrderIntent

```python
intent = OrderIntent(
    strategy_id="momentum_strategy",
    broker_account_id="alpaca_main",
    symbol="BTC/USD",
    side="buy",
    qty=0.5,
    asset_class="CRYPTO",
    estimated_slippage=0.0008,  # Pre-computed or fetched
    metadata={"tenant_id": "...", "uid": "..."},
)
```

#### Execution Flow

1. **Intent Received**: Execution engine receives OrderIntent
2. **Smart Routing**: Check spread and estimate slippage
3. **Cost Decision**: 
   - If spread > 0.1% → Downgrade to WAIT
   - If spread ≤ 0.1% → Proceed to risk checks
4. **Risk Validation**: Standard risk checks (position limits, daily trades, kill switch)
5. **Broker Routing**: Route to appropriate broker (Alpaca supports all asset classes)
6. **Persistence**: Write to both ledger and portfolio history

#### New Status: "downgraded"

```python
result = engine.execute_intent(intent=intent)

if result.status == "downgraded":
    print(f"Signal downgraded: {result.routing.reason}")
    print(f"Spread: {result.routing.spread_pct:.4%}")
```

## Usage Examples

### Example 1: Equity Strategy with Cost Awareness

```python
from functions.strategies.base_strategy import BaseStrategy, TradingSignal, SignalType, AssetClass

class CostAwareEquityStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(config={"max_slippage_pct": 0.001})  # 0.1% threshold
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        # Check if transaction costs are acceptable
        if self.should_downgrade_signal(market_data):
            return TradingSignal(
                signal_type=SignalType.WAIT,
                symbol=market_data["symbol"],
                asset_class=AssetClass.EQUITY,
                reasoning="Spread too wide - waiting for better execution",
                estimated_slippage=self.estimate_slippage(market_data),
            )
        
        # Generate trading signal
        return TradingSignal(
            signal_type=SignalType.BUY,
            symbol=market_data["symbol"],
            asset_class=AssetClass.EQUITY,
            confidence=0.85,
            reasoning="Strong buy signal with acceptable execution costs",
            estimated_slippage=self.estimate_slippage(market_data),
        )
```

### Example 2: Multi-Asset Portfolio Strategy

```python
class MultiAssetStrategy(BaseStrategy):
    def __init__(self):
        super().__init__(config={
            "max_slippage_pct": 0.001,
            "supported_assets": [AssetClass.EQUITY, AssetClass.FOREX, AssetClass.CRYPTO],
        })
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        symbol = market_data["symbol"]
        asset_class = BaseStrategy.detect_asset_class(symbol)
        
        # Check costs before generating signal
        if self.should_downgrade_signal(market_data):
            return TradingSignal(
                signal_type=SignalType.WAIT,
                symbol=symbol,
                asset_class=asset_class,
                reasoning=f"High costs for {asset_class.value}",
                estimated_slippage=self.estimate_slippage(market_data),
            )
        
        # Asset-specific logic
        if asset_class == AssetClass.CRYPTO:
            # Crypto trading logic
            return self._evaluate_crypto(market_data)
        elif asset_class == AssetClass.FOREX:
            # Forex trading logic
            return self._evaluate_forex(market_data)
        else:
            # Equity trading logic
            return self._evaluate_equity(market_data)
```

### Example 3: Execution Engine Setup

```python
from backend.execution.engine import (
    ExecutionEngine,
    AlpacaBroker,
    SmartRouter,
    RiskManager,
    OrderIntent,
)

# Initialize components
broker = AlpacaBroker()
router = SmartRouter(max_spread_pct=0.001)  # 0.1% threshold
risk_manager = RiskManager()

# Create execution engine with smart routing
engine = ExecutionEngine(
    broker=broker,
    router=router,
    risk=risk_manager,
    enable_smart_routing=True,  # Enable cost optimization
    dry_run=False,
)

# Execute multi-asset order
intent = OrderIntent(
    strategy_id="multi_asset_momentum",
    broker_account_id="alpaca_main",
    symbol="EUR/USD",
    side="buy",
    qty=10000.0,
    asset_class="FOREX",
    metadata={
        "tenant_id": "acme_corp",
        "uid": "user_12345",
    },
)

result = engine.execute_intent(intent=intent)

if result.status == "downgraded":
    print(f"❌ Trade blocked: {result.routing.reason}")
    print(f"   Spread: {result.routing.spread_pct:.4%}")
elif result.status == "placed":
    print(f"✅ Order placed: {result.broker_order_id}")
    print(f"   Estimated slippage: {result.routing.estimated_slippage:.4%}")
```

## Configuration

### Environment Variables

- `EXEC_DRY_RUN`: Enable dry-run mode (default: 1)
- `EXEC_KILL_SWITCH`: Emergency kill switch (default: 0)
- `EXEC_MAX_POSITION_QTY`: Max position size (default: 100)
- `EXEC_MAX_DAILY_TRADES`: Max trades per day (default: 50)
- `EXEC_TENANT_ID`: Default tenant ID for ledger writes
- `EXEC_UID`: Default user ID for portfolio history

### Strategy Config

```python
config = {
    "max_slippage_pct": 0.001,  # 0.1% default threshold
    "supported_assets": [
        AssetClass.EQUITY,
        AssetClass.FOREX,
        AssetClass.CRYPTO,
    ],
}

strategy = MyStrategy(config=config)
```

## Performance Impact

### Benefits

1. **Alpha Protection**: Prevents trades when execution costs exceed expected returns
2. **Cost Transparency**: All trades include estimated slippage for analysis
3. **Tax Efficiency**: Portfolio history enables accurate tax reporting
4. **Multi-Asset Flexibility**: Single platform for all asset classes

### Overhead

- **Latency**: +50-100ms per trade for quote fetch (can be pre-computed in strategy)
- **API Calls**: +1 market data call per trade (if not pre-computed)
- **Storage**: +1 Firestore write per trade for portfolio history

## Monitoring

### Key Metrics

1. **Downgrade Rate**: % of signals downgraded due to high costs
2. **Average Slippage**: Mean estimated slippage across all trades
3. **Cost Savings**: Trades avoided due to high transaction costs
4. **Asset Class Distribution**: Trade volume by asset class

### Logging

All execution decisions are logged with structured data:

```json
{
  "event": "exec.smart_routing",
  "should_execute": false,
  "reason": "Spread 0.15% exceeds threshold 0.10%",
  "spread_pct": 0.0015,
  "estimated_slippage": 0.0015,
  "downgraded": true,
  "symbol": "BTC/USD",
  "asset_class": "CRYPTO"
}
```

## Testing

Comprehensive test suite in `tests/test_multi_asset_execution.py`:

```bash
# Run all tests
pytest tests/test_multi_asset_execution.py -v

# Run specific test class
pytest tests/test_multi_asset_execution.py::TestSmartRouter -v
```

### Test Coverage

- ✅ Multi-asset OrderIntent creation
- ✅ Slippage estimation from bid-ask spreads
- ✅ Signal downgrade logic (spread > 0.1%)
- ✅ Smart routing integration with execution engine
- ✅ BaseStrategy multi-asset methods
- ✅ Asset class auto-detection
- ✅ Portfolio history persistence
- ✅ End-to-end integration flow

## Migration Guide

### For Existing Strategies

1. **Add asset_class to signals**:
   ```python
   # Before
   signal = TradingSignal(signal_type=SignalType.BUY, confidence=0.8)
   
   # After
   signal = TradingSignal(
       signal_type=SignalType.BUY,
       symbol="AAPL",
       asset_class=AssetClass.EQUITY,
       confidence=0.8,
   )
   ```

2. **Include bid/ask in market_data**:
   ```python
   market_data = {
       "symbol": "AAPL",
       "price": 150.0,
       "bid": 149.95,  # Add
       "ask": 150.05,  # Add
   }
   ```

3. **Optional: Add cost checking**:
   ```python
   if self.should_downgrade_signal(market_data):
       return TradingSignal(signal_type=SignalType.WAIT, ...)
   ```

### For Existing Execution Code

OrderIntent API is backward compatible. New fields are optional:

```python
# Old code still works
intent = OrderIntent(
    strategy_id="s1",
    broker_account_id="acct1",
    symbol="SPY",
    side="buy",
    qty=10,
)

# New fields optional
intent = OrderIntent(
    strategy_id="s1",
    broker_account_id="acct1",
    symbol="SPY",
    side="buy",
    qty=10,
    asset_class="EQUITY",  # Optional, defaults to EQUITY
    estimated_slippage=0.0005,  # Optional, will be fetched if not provided
)
```

## Security & Compliance

### Tax Reporting

Portfolio history at `users/{uid}/portfolio/history/trades/` includes:

- Cost basis calculation
- Tax lot method (FIFO default)
- Trading date for tax year tracking
- Detailed trade metadata

### Audit Trail

Every execution decision is logged with:

- Intent details (strategy, symbol, qty)
- Cost analysis (spread, slippage)
- Risk checks (position limits, daily trades)
- Routing decision (execute or downgrade)
- Broker confirmation (order ID, fill price)

### Data Retention

- **Ledger**: Immutable, append-only
- **Portfolio History**: User-accessible for tax/compliance
- **Logs**: Structured logs for audit and debugging

## Future Enhancements

1. **Dynamic Thresholds**: Adjust slippage threshold based on market regime
2. **Historical Cost Analysis**: Track actual slippage vs. estimated
3. **Broker Routing**: Route to cheapest broker per asset class
4. **Limit Order Optimization**: Automatically use limit orders for high-spread assets
5. **Cross-Asset Arbitrage**: Detect and exploit price inefficiencies

## Support

For issues or questions:

1. Check logs: `exec.smart_routing` and `exec.intent_received`
2. Review test cases: `tests/test_multi_asset_execution.py`
3. Verify configuration: Environment variables and strategy config
4. Test with dry_run=True before production deployment

---

**Implementation Date**: December 30, 2025
**Version**: 1.0
**Status**: ✅ Production Ready
