# 0DTE Gamma Scalper Strategy

A delta-neutral gamma scalping strategy for Zero Days to Expiration (0DTE) options.

## Strategy Overview

This strategy implements a sophisticated gamma scalping approach that:

1. **Maintains Delta Neutrality**: Continuously monitors and hedges portfolio delta exposure
2. **Adapts to Market Regime**: Adjusts hedging frequency based on market Gamma Exposure (GEX)
3. **Manages Intraday Risk**: Exits all positions before market close to avoid volatility
4. **Uses High Precision**: All calculations use Python's Decimal type for accuracy

## Core Logic

### 1. Net Portfolio Delta Calculation

The strategy calculates the net delta exposure across all open positions:

```
Net Delta = Σ (position_delta × quantity)
```

Where:
- `position_delta`: The delta of each options position
- `quantity`: Number of contracts held

### 2. Hedging Rules

**Base Rule**: If `abs(Net Delta) > HEDGING_THRESHOLD`, trigger a hedge trade

- **Standard Threshold**: 0.15 (default)
- **Negative GEX Threshold**: 0.10 (tighter hedging when market is short gamma)

The hedge quantity is calculated to return Net Delta to zero:
```
Hedge Quantity = -Net Delta
```

### 3. Market Regime Detection (GEX)

The strategy ingests Gamma Exposure (GEX) data from Firestore:

- **Positive GEX**: Market is long gamma → Standard hedging threshold (0.15)
- **Negative GEX**: Market is short gamma → Tighter threshold (0.10) for more frequent hedging

This adaptive approach increases hedging frequency during volatile, gamma-negative regimes.

### 4. Time-Based Exit

**Exit Time**: 3:45 PM ET (15 minutes before market close)

All positions are automatically closed at this time to avoid:
- Market-on-Close (MOC) order imbalances
- End-of-day volatility spikes
- Overnight risk on 0DTE positions

## Safety Features

### Precision
- All financial calculations use `Decimal` type
- Avoids floating-point arithmetic errors
- Ensures accurate delta and P&L calculations

### Risk Management
- Automatic position exit before market close
- Rate limiting on hedge orders (minimum 60 seconds between hedges)
- Zero division protection
- Validates underlying price before hedging

### State Management
- Tracks all open positions with symbol, delta, quantity, and price
- Maintains GEX cache to reduce Firestore queries
- Records last hedge time for rate limiting

## Configuration

### Environment Variables

```bash
# GEX Value (optional, can be sourced from Firestore in production)
GEX_VALUE=-15000.0

# Firestore Configuration
FIREBASE_PROJECT_ID=your-project-id
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### Strategy Parameters

Configurable in `strategy.py`:

```python
HEDGING_THRESHOLD = Decimal("0.15")  # Base delta threshold
HEDGING_THRESHOLD_NEGATIVE_GEX = Decimal("0.10")  # Threshold when GEX < 0
EXIT_TIME_ET = time(15, 45, 0)  # Exit time (3:45 PM ET)
```

## Firestore Integration

### Expected Data Structure

**Collection**: `market_regime`
**Document**: `SPX_GEX`

```json
{
  "gex_value": -15000.0,
  "last_update": "2025-12-30T14:30:00Z",
  "symbol": "SPX",
  "source": "market_data_provider"
}
```

### Production Implementation

To enable Firestore GEX fetching, uncomment the following in `_fetch_gex_from_firestore()`:

```python
from google.cloud import firestore

db = firestore.Client()
doc_ref = db.collection('market_regime').document('SPX_GEX')
doc = doc_ref.get()
if doc.exists:
    gex_value = doc.to_dict().get('gex_value')
    _last_gex_value = _to_decimal(gex_value)
    _last_gex_update = datetime.now(tz=ZoneInfo("UTC"))
```

## Protocol Interface

### Input: MarketEvent

The strategy receives market events conforming to `backend.strategy_runner.protocol.MarketEvent`:

```python
{
  "protocol": "v1",
  "type": "market_event",
  "event_id": "evt_12345",
  "ts": "2025-12-30T14:30:00Z",
  "symbol": "SPY251230C00500000",  # Options symbol
  "source": "alpaca",
  "payload": {
    "delta": 0.65,
    "price": 2.50,
    "quantity": 10,
    "underlying_price": 495.50,
    "greeks": {
      "delta": 0.65,
      "gamma": 0.05,
      "theta": -0.10
    }
  }
}
```

### Output: OrderIntent

The strategy returns order intents conforming to `backend.strategy_runner.protocol.OrderIntent`:

```python
{
  "protocol": "v1",
  "type": "order_intent",
  "intent_id": "hedge_SPY_abc123",
  "event_id": "evt_12345",
  "ts": "2025-12-30T14:30:00Z",
  "symbol": "SPY",
  "side": "sell",
  "qty": 6.5,
  "order_type": "market",
  "time_in_force": "day",
  "client_tag": "0dte_gamma_scalper_hedge",
  "metadata": {
    "reason": "delta_hedge",
    "net_delta_before": "0.65",
    "hedge_qty": "-6.5",
    "underlying_price": "495.50",
    "hedging_threshold": "0.15",
    "gex_value": "-15000.0",
    "strategy": "0dte_gamma_scalper"
  }
}
```

## Usage

### Running the Strategy

```bash
# Set environment variables
export FIREBASE_PROJECT_ID=your-project-id
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
export GEX_VALUE=-15000.0  # Optional: override GEX

# Run with the strategy harness
cd /workspace
python -m backend.strategy_runner.harness \
  --strategy backend/strategy_runner/examples/gamma_scalper_0dte \
  --events backend/strategy_runner/examples/gamma_scalper_0dte/events.ndjson
```

### Testing

```bash
# Run strategy protocol tests
pytest tests/test_strategy_protocol.py

# Test the strategy with sample events
python -m backend.strategy_runner.examples.gamma_scalper_0dte.test_strategy
```

## Example Scenarios

### Scenario 1: Delta Exceeds Threshold

**Initial State**:
- 10 SPY call contracts, delta = 0.65 each
- Net Delta = 10 × 0.65 = 6.5
- Threshold = 0.15

**Result**: `abs(6.5) > 0.15` → Trigger hedge
- Create sell order for 6 shares of SPY (rounds 6.5 to 6)
- New Net Delta ≈ 0.5

### Scenario 2: Negative GEX Environment

**Initial State**:
- GEX = -20000 (market is short gamma)
- Net Delta = 0.12
- Standard Threshold = 0.15
- Negative GEX Threshold = 0.10

**Result**: `abs(0.12) > 0.10` → Trigger hedge (tighter threshold due to negative GEX)

### Scenario 3: Market Close Exit

**Initial State**:
- Current Time = 3:45 PM ET
- Open positions: 10 SPY calls, 5 SPY puts

**Result**: Exit all positions
- Sell 10 call contracts
- Buy back 5 put contracts
- Clear portfolio

## Performance Considerations

### Latency
- In-memory position tracking (no database queries per event)
- Cached GEX value (reduces Firestore round-trips)
- Efficient Decimal arithmetic

### Scalability
- Stateful design (maintains positions across events)
- Rate limiting prevents excessive hedging
- Minimal external dependencies during event processing

## Risk Disclaimer

This strategy is provided for educational and research purposes. Key risks include:

1. **Execution Risk**: Slippage and delays in hedge execution
2. **Model Risk**: Delta estimates may be inaccurate
3. **Gamma Risk**: Rapid delta changes between hedges
4. **Liquidity Risk**: Difficulty hedging large positions
5. **Technology Risk**: System failures or connectivity issues

Always test thoroughly in paper trading before using real capital.

## References

- Strategy Runner Protocol: `backend/strategy_runner/protocol.py`
- Market Event Schema: `backend.strategy_runner.protocol.MarketEvent`
- Order Intent Schema: `backend.strategy_runner.protocol.OrderIntent`
- Firestore Data Model: `/workspace/FIRESTORE_DATA_MODEL.md`

## License

See repository root for license information.
