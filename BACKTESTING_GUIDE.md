# Strategy Backtesting Guide

## Overview

The backtesting engine allows you to test trading strategies on historical market data before deploying them live. This helps you:

- **Validate Strategy Logic**: Ensure your strategy behaves as expected
- **Measure Performance**: Calculate key metrics like Sharpe Ratio, Max Drawdown, and Win Rate
- **Compare to Benchmark**: See how your strategy performs vs. buy-and-hold
- **Identify Issues**: Discover edge cases and bugs before going live

## Architecture

### Components

1. **Backtester Engine** (`functions/backtester.py`)
   - Fetches historical 1-minute bars from Alpaca
   - Simulates strategy execution with realistic position tracking
   - Calculates comprehensive performance metrics
   - Tracks equity curves and trade history

2. **React Frontend** (`frontend/src/components/BacktestChart.tsx`)
   - Interactive equity curve visualization
   - Performance metrics dashboard
   - Trade history table
   - Comparison with buy-and-hold benchmark

3. **Cloud Function** (`functions/main.py`)
   - HTTP endpoint to run backtests
   - Handles long-running simulations
   - Returns structured results

## Quick Start

### 1. Set Up Environment

Ensure you have Alpaca API credentials:

```bash
export APCA_API_KEY_ID="your_api_key"
export APCA_API_SECRET_KEY="your_secret_key"
```

### 2. Run a Backtest (Python)

```python
from backtester import Backtester
from strategies.gamma_scalper import GammaScalper

# Initialize strategy
strategy = GammaScalper(config={
    "threshold": 0.15,
    "gex_positive_multiplier": 0.5,
    "gex_negative_multiplier": 1.5
})

# Create backtester
backtester = Backtester(
    strategy=strategy,
    symbol="SPY",
    start_date="2024-11-01",
    end_date="2024-12-01",
    initial_capital=100000.0
)

# Run backtest
results = backtester.run()

# Print metrics
print(f"Total Return: {results['metrics']['total_return']:.2%}")
print(f"Sharpe Ratio: {results['metrics']['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {results['metrics']['max_drawdown']:.2%}")
print(f"Win Rate: {results['metrics']['win_rate']:.2%}")
```

### 3. Run via Web Interface

1. Navigate to the Backtesting page in the UI
2. Select your strategy (e.g., "0DTE Gamma Scalper")
3. Configure parameters:
   - **Symbol**: SPY, QQQ, etc.
   - **Start Date**: Beginning of backtest period
   - **End Date**: End of backtest period
   - **Initial Capital**: Starting portfolio value
4. Click "Run Backtest"
5. Review results in the interactive dashboard

## Performance Metrics

### Returns

- **Total Return**: Overall percentage gain/loss
- **Benchmark Return**: Buy-and-hold return for comparison
- **Alpha**: Excess return vs. benchmark (positive is good)

### Risk Metrics

- **Sharpe Ratio**: Risk-adjusted return
  - \> 1.0: Good
  - \> 2.0: Very Good
  - \> 3.0: Excellent
  - Formula: `(Mean Return / Std Dev Return) * sqrt(252 * 390)`
  
- **Max Drawdown**: Largest peak-to-trough decline
  - Lower is better
  - Shows worst-case portfolio decline

### Trade Statistics

- **Win Rate**: Percentage of profitable trades
- **Total Trades**: Number of completed round trips
- **Average Win**: Mean profit per winning trade
- **Average Loss**: Mean loss per losing trade
- **Profit Factor**: `Avg Win / |Avg Loss|`
  - \> 1.0: Strategy is profitable
  - \> 2.0: Strong edge

## Creating Custom Strategies

### Strategy Interface

All strategies must inherit from `BaseStrategy` and implement the `evaluate()` method:

```python
from strategies.base_strategy import BaseStrategy, SignalType, TradingSignal

class MyStrategy(BaseStrategy):
    def __init__(self, config=None):
        super().__init__(config)
        self.my_param = config.get("my_param", 0.5)
    
    def evaluate(self, market_data, account_snapshot, regime=None):
        """
        Evaluate market conditions and return a trading signal.
        
        Args:
            market_data: Dict with price, volume, greeks, etc.
            account_snapshot: Dict with equity, cash, positions
            regime: Optional market regime (e.g., "LONG_GAMMA")
        
        Returns:
            TradingSignal with type, confidence, and reasoning
        """
        # Your logic here
        price = market_data["price"]
        
        if some_buy_condition:
            return TradingSignal(
                signal_type=SignalType.BUY,
                confidence=0.5,  # 50% of buying power
                reasoning="Buy condition met",
                metadata={"price": price}
            )
        
        return TradingSignal(
            signal_type=SignalType.HOLD,
            confidence=0.0,
            reasoning="No action"
        )
```

### Signal Types

- **BUY**: Open long position (confidence = allocation %)
- **SELL**: Close positions or open short
- **HOLD**: No action
- **CLOSE_ALL**: Exit all positions immediately

### Market Data Structure

```python
market_data = {
    "symbol": "SPY",
    "price": 450.25,
    "timestamp": "2024-01-15T14:30:00Z",
    "open": 450.00,
    "high": 451.00,
    "low": 449.50,
    "close": 450.25,
    "volume": 5000000,
    "greeks": {},  # Options greeks if available
    "gex_status": "neutral"  # GEX regime
}
```

### Account Snapshot Structure

```python
account_snapshot = {
    "equity": "105000.00",
    "buying_power": "52500.00",
    "cash": "50000.00",
    "positions": [
        {
            "symbol": "SPY",
            "qty": 100.0,
            "entry_price": 450.00,
            "greeks": {...}
        }
    ]
}
```

## Example Strategies

### 1. 0DTE Gamma Scalper

Located in `functions/strategies/gamma_scalper.py`

**Logic:**
- Maintains delta-neutral portfolio
- Rebalances when |delta| > threshold
- Adjusts allocation based on GEX regime
- Exits all positions at 3:45 PM ET

**Use Case:** Capitalize on market maker hedging flows

### 2. Example Strategy

Located in `functions/strategies/example_strategy.py`

**Logic:**
- Simple moving average crossover
- Buys when price > MA
- Sells when price < MA

**Use Case:** Educational template for new strategies

## Best Practices

### 1. Data Requirements

- **Minimum Period**: 30 days for reliable statistics
- **Recommended**: 3-6 months for production strategies
- **Resolution**: 1-minute bars provide good balance

### 2. Interpreting Results

**Good Strategy Characteristics:**
- Sharpe Ratio > 1.0
- Max Drawdown < 20%
- Win Rate > 50% (or high profit factor if lower)
- Positive alpha vs. benchmark
- Consistent equity curve (not just one big win)

**Red Flags:**
- Very high Sharpe (> 5.0): May indicate overfitting
- Max Drawdown > 50%: Too risky
- Few trades (< 10): Insufficient statistical significance
- Equity curve is mostly flat then spikes: Likely overfitted

### 3. Avoiding Overfitting

- Test on out-of-sample data (different time periods)
- Keep strategy logic simple
- Avoid excessive parameter tuning
- Use walk-forward testing
- Test across multiple symbols

### 4. Limitations

Current limitations to be aware of:

1. **Slippage**: Not yet implemented (assumes fills at close price)
2. **Commissions**: Not yet implemented (assumes zero commissions)
3. **Market Impact**: Assumes your orders don't move the market
4. **Data Quality**: Limited to Alpaca's 1-minute bars
5. **Lookahead Bias**: Be careful not to use future information

## Advanced Usage

### Custom Metrics

You can extend the backtester to calculate additional metrics:

```python
class MyBacktester(Backtester):
    def _calculate_metrics(self):
        # Call parent method
        metrics = super()._calculate_metrics()
        
        # Add custom metrics
        metrics["custom_metric"] = self._calculate_my_metric()
        
        return metrics
```

### Event-Driven Backtesting

For strategies using the protocol pattern (like `strategy_runner` examples):

```python
# Your strategy in backend/strategy_runner/examples/my_strategy/strategy.py
def on_market_event(event):
    # Process event
    # Return OrderIntent objects
    pass
```

### Multi-Symbol Backtesting

Extend the backtester to test on multiple symbols simultaneously:

```python
# Future enhancement - not yet implemented
backtester = MultiSymbolBacktester(
    strategy=strategy,
    symbols=["SPY", "QQQ", "IWM"],
    # ...
)
```

## Deployment

### Local Testing

```bash
cd functions
python backtester.py
```

### Cloud Function Deployment

```bash
firebase deploy --only functions:run_backtest
```

### Frontend Integration

The backtesting page is available at `/backtesting` in the web app.

## Troubleshooting

### Issue: "Alpaca API credentials not configured"

**Solution:** Set environment variables:
```bash
export APCA_API_KEY_ID="your_key"
export APCA_API_SECRET_KEY="your_secret"
```

### Issue: "No data available for backtesting"

**Solution:**
- Check date range (markets closed on weekends/holidays)
- Verify symbol is valid
- Ensure Alpaca account has data access

### Issue: Backtest times out

**Solution:**
- Reduce date range
- Use lower resolution data
- Increase Cloud Function timeout

### Issue: Results seem unrealistic

**Solution:**
- Check for lookahead bias in strategy
- Verify signal confidence values (should be 0-1)
- Review trade execution logic
- Compare with benchmark for sanity check

## Testing

Run the test suite:

```bash
# Run all backtester tests
pytest tests/test_backtester.py -v

# Run specific test
pytest tests/test_backtester.py::TestBacktester::test_backtester_run_hold_strategy -v

# Run with coverage
pytest tests/test_backtester.py --cov=functions.backtester --cov-report=html
```

## API Reference

### Backtester Class

```python
class Backtester:
    def __init__(
        strategy: BaseStrategy,
        symbol: str = "SPY",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        initial_capital: float = 100000.0,
        commission: float = 0.0,
        slippage: float = 0.0,
        alpaca_api_key: Optional[str] = None,
        alpaca_secret_key: Optional[str] = None
    )
    
    def run() -> Dict[str, Any]:
        """Run the backtest and return results."""
        pass
    
    def fetch_data() -> List[Dict[str, Any]]:
        """Fetch historical data from Alpaca."""
        pass
```

### Results Structure

```python
results = {
    "metrics": {
        "initial_capital": 100000.0,
        "final_equity": 105000.0,
        "total_return": 0.05,
        "benchmark_return": 0.03,
        "alpha": 0.02,
        "sharpe_ratio": 1.5,
        "max_drawdown": 0.08,
        "win_rate": 0.65,
        "total_trades": 20,
        "winning_trades": 13,
        "losing_trades": 7,
        "avg_win": 500.0,
        "avg_loss": -200.0,
        "profit_factor": 2.5
    },
    "equity_curve": [
        {
            "timestamp": "2024-01-01T09:30:00Z",
            "equity": 100000.0,
            "cash": 100000.0,
            "position_value": 0.0,
            "num_positions": 0
        },
        # ... more points
    ],
    "benchmark_curve": [
        {
            "timestamp": "2024-01-01T09:30:00Z",
            "equity": 100000.0
        },
        # ... more points
    ],
    "trades": [
        {
            "timestamp": "2024-01-01T10:00:00Z",
            "symbol": "SPY",
            "side": "buy",
            "quantity": 100.0,
            "price": 450.0,
            "type": "entry"
        },
        # ... more trades
    ],
    "config": {
        "symbol": "SPY",
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "initial_capital": 100000.0,
        "strategy": "GammaScalper"
    }
}
```

## Future Enhancements

Planned features:

1. **Slippage Modeling**: Realistic fill prices
2. **Commission Tracking**: Include trading costs
3. **Multi-Symbol Support**: Test on portfolios
4. **Walk-Forward Testing**: Automatic out-of-sample validation
5. **Monte Carlo Simulation**: Probabilistic outcome analysis
6. **Transaction Cost Analysis**: Detailed cost breakdown
7. **Options Data**: Support for options backtesting
8. **Custom Timeframes**: Support hourly, daily bars

## Support

For issues or questions:
- Check the test suite for usage examples
- Review existing strategy implementations
- Consult the [Strategy Development Guide](./STRATEGY_INTEGRATION_SUMMARY.md)

## License

Part of the AgentTrader platform.
