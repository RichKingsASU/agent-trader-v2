# Backtesting Module

## Overview

The backtesting module provides a comprehensive framework for testing trading strategies on historical data before deploying them live.

## Key Features

✅ **Historical Data Integration**: Fetches 1-minute bars from Alpaca  
✅ **Realistic Simulation**: Accurate position tracking and P&L calculation  
✅ **Performance Metrics**: Sharpe Ratio, Max Drawdown, Win Rate, and more  
✅ **Benchmark Comparison**: Automatic comparison vs. buy-and-hold  
✅ **Trade Analytics**: Detailed trade history and statistics  
✅ **Visual Dashboard**: Interactive React component with charts

## Options Modeling in Backtests (Safety-First)

Backtests in this repo are designed to be **safe** (no broker execution) and to support
options-style strategies using progressively more realistic modeling approaches:

- **Proxy Greeks (CURRENT DEFAULT)**: `functions/strategies/backtester.py` uses `GreeksSimulator`
  to generate plausible delta/gamma/theta/vega for each timestep based on the underlying price.
  This supports “options-like” decision logic without requiring an options chain.
- **Real Options Snapshots (AVAILABLE AS DATA, NOT WIRED INTO BACKTESTER YET)**:
  the ingestion pipeline fetches Alpaca options chain snapshots and stores them in
  `public.alpaca_option_snapshots` (see `backend/streams/alpaca_options_chain_ingest.py`).
- **Synthetic Payoff (FUTURE EXTENSION)**: strategy payoff can be modeled directly from
  a synthetic option price model or expiry payoff. Not currently implemented.

## Quick Start

### 1. Set Environment Variables

```bash
export APCA_API_KEY_ID="your_api_key"
export APCA_API_SECRET_KEY="your_secret_key"
```

### 2. Run Example Backtest

```bash
python scripts/run_backtest_example.py
```

### 2b. Single-Command Backtest (Strategy, Symbol, Date Range)

```bash
python scripts/backtest.py --strategy GammaScalper --symbol SPY --start 2025-12-01 --end 2025-12-31
```

### 3. Use in Code

```python
from backtester import Backtester
from strategies.gamma_scalper import GammaScalper

# Initialize strategy
strategy = GammaScalper(config={
    "threshold": 0.15,
    "gex_positive_multiplier": 0.5,
    "gex_negative_multiplier": 1.5
})

# Create and run backtester
backtester = Backtester(
    strategy=strategy,
    symbol="SPY",
    start_date="2024-11-01",
    end_date="2024-12-01",
    initial_capital=100000.0
)

results = backtester.run()
```

## Components

### 1. Backtester Engine (`backtester.py`)

Main backtesting engine with the following classes:

- **`Backtester`**: Main engine for running backtests
- **`BacktestAccount`**: Simulates a trading account
- **`BacktestPosition`**: Represents a single position

### 2. React Components

- **`BacktestChart.tsx`**: Main visualization component
- **`Backtesting.tsx`**: Full-page interface with configuration

### 3. Cloud Function

- **`run_backtest`**: HTTP endpoint for running backtests from the UI

## Performance Metrics

### Returns
- **Total Return**: Overall percentage gain/loss
- **Benchmark Return**: Buy-and-hold performance
- **Alpha**: Excess return vs benchmark

### Risk
- **Sharpe Ratio**: Risk-adjusted return (higher is better)
- **Max Drawdown**: Largest peak-to-trough decline (lower is better)

### Trade Statistics
- **Win Rate**: Percentage of profitable trades
- **Average Win/Loss**: Mean profit/loss per trade
- **Profit Factor**: Ratio of gross profit to gross loss

## Testing

Run the test suite:

```bash
pytest tests/test_backtester.py -v
```

All tests passed ✅ (17/17)

## Results Structure

```python
{
    "metrics": {
        "initial_capital": 100000.0,
        "final_equity": 105000.0,
        "total_return": 0.05,
        "sharpe_ratio": 1.5,
        "max_drawdown": 0.08,
        "win_rate": 0.65,
        # ... more metrics
    },
    "equity_curve": [...],
    "benchmark_curve": [...],
    "trades": [...],
    "config": {...}
}
```

## Best Practices

1. **Test Period**: Use at least 30 days, ideally 3-6 months
2. **Multiple Symbols**: Test on different symbols to avoid overfitting
3. **Out-of-Sample**: Test on periods not used for strategy development
4. **Realistic Expectations**: Account for slippage and commissions in live trading

## Documentation

See [BACKTESTING_GUIDE.md](../BACKTESTING_GUIDE.md) for comprehensive documentation.

## Support

- GitHub Issues: Report bugs and request features
- Tests: See `tests/test_backtester.py` for examples
- Example: Run `scripts/run_backtest_example.py`
