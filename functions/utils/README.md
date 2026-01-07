# Trading Strategy Utilities

This directory contains utility modules for trading strategies and risk management.

## Monte Carlo Stress Testing

### Overview

The Monte Carlo stress testing engine (`monte_carlo.py`) provides comprehensive risk analysis for trading strategies before deployment to live markets. It simulates thousands of market scenarios using Geometric Brownian Motion with injected Black Swan events to identify potential vulnerabilities.

### Key Features

1. **Geometric Brownian Motion (GBM) Price Generation**
   - Simulates realistic price paths for multiple assets
   - Configurable drift and volatility parameters
   - Support for correlated asset movements

2. **Black Swan Event Injection**
   - Random crash events in 10% of simulations (configurable)
   - Crashes range from -10% to -20% market declines
   - Simulates "correlation convergence" where all assets decline together

3. **Dynamic Correlation Modeling**
   - Normal market: 0.5 correlation between sectors
   - Crisis mode: 0.95 correlation (sectors move together)
   - Smooth transitions over 5-day windows

4. **Comprehensive Risk Metrics**
   - **Value at Risk (VaR)**: Loss threshold at 95% and 99% confidence
   - **Conditional VaR (CVaR)**: Expected loss in tail scenarios
   - **Maximum Drawdown**: Worst peak-to-trough decline
   - **Sharpe Ratio**: Risk-adjusted returns
   - **Survival Rate**: % of paths avoiding liquidation
   - **Recovery Time**: Days to recover from drawdowns

5. **Strategy Pass/Fail Criteria**
   ```
   ✅ PASS if:
   - VaR(95%) ≤ 15%
   - Survival Rate ≥ 99%
   - Max Drawdown ≤ 25%
   - Sharpe Ratio ≥ 1.0
   
   ❌ FAIL if any criterion is violated
   ```

### Usage

#### Quick Start

```python
from functions.utils.monte_carlo import MonteCarloSimulator, SimulationParameters
from functions.strategies.sector_rotation import SectorRotationStrategy

# 1. Create strategy
strategy = SectorRotationStrategy(config={
    "lookback_days": 20,
    "num_top_sectors": 3,
    "crash_threshold": -0.05,
})

# 2. Configure simulation
params = SimulationParameters(
    num_simulations=1000,
    num_days=252,
    initial_capital=100000.0,
    black_swan_probability=0.10,
)

# 3. Run stress test
simulator = MonteCarloSimulator(params)
paths, risk_metrics = simulator.simulate_strategy(
    strategy_evaluate_fn=strategy.evaluate,
    strategy_config={},
)

# 4. Check results
if risk_metrics.passes_stress_test:
    print("✅ Strategy ready for live trading")
else:
    print("❌ Strategy failed stress test:")
    for reason in risk_metrics.failure_reasons:
        print(f"  - {reason}")
```

#### Using the Stress Test Runner

```python
from functions.stress_test_runner import run_stress_test

results = run_stress_test(
    strategy_name="sector_rotation",
    strategy_config={"lookback_days": 20},
    simulation_params={"num_simulations": 1000},
    save_to_firestore=True,
    tenant_id="user-123"
)

print(results['report']['interpretation'])
```

#### Command Line

```bash
python scripts/run_stress_test.py
```

### API Endpoint

```typescript
// Frontend usage
const response = await fetch('/api/analytics/stress-test?tenant_id=demo', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    strategy_name: 'sector_rotation',
    num_simulations: 1000,
    num_days: 252,
    black_swan_probability: 0.10,
  })
});

const results = await response.json();
console.log(results.passes_stress_test);
```

### Simulation Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `num_simulations` | 1000 | Number of Monte Carlo paths |
| `num_days` | 252 | Trading days to simulate |
| `initial_capital` | 100,000 | Starting portfolio value |
| `base_drift` | 0.10 | Expected annual return (10%) |
| `base_volatility` | 0.20 | Annual volatility (20%) |
| `black_swan_probability` | 0.10 | % of paths with crash events |
| `crash_magnitude_min` | -0.10 | Minimum crash size (-10%) |
| `crash_magnitude_max` | -0.20 | Maximum crash size (-20%) |
| `normal_correlation` | 0.50 | Asset correlation (normal) |
| `crisis_correlation` | 0.95 | Asset correlation (crisis) |
| `slippage_bps` | 5.0 | Transaction slippage (5 bps) |

### Output Format

The simulator returns:

```python
{
    "success": True,
    "metadata": {
        "num_simulations": 1000,
        "simulation_timestamp": "2025-12-30T10:00:00"
    },
    "risk_metrics": {
        "var_95": 0.12,  # 12% VaR
        "cvar_95": 0.15,  # 15% Expected Shortfall
        "survival_rate": 0.998,  # 99.8% survival
        "mean_sharpe": 1.2,
        "worst_drawdown": 0.22,  # 22% max drawdown
        "passes_stress_test": True,
        "failure_reasons": []
    },
    "paths_summary": [
        {
            "path_id": "sim_abc123",
            "is_black_swan": False,
            "final_equity": 112500,
            "total_return": 0.125,
            "max_drawdown": 0.08,
            "sharpe_ratio": 1.5
        },
        # ... 999 more paths
    ]
}
```

### Visualization

The stress test UI (`frontend/src/pages/StressTest.tsx`) provides:

- **Risk Metrics Cards**: VaR, CVaR, Sharpe, Survival Rate
- **Risk Bar Chart**: Visual comparison vs. thresholds
- **Equity Distribution**: Histogram of final portfolio values
- **Performance Table**: Detailed metrics breakdown

### Performance Considerations

- **Memory**: Each path stores ~2KB of data. 1,000 paths ≈ 2MB
- **CPU**: ~10-30 seconds for 1,000 simulations on modern hardware
- **Optimization**: Set `save_all_paths=False` to reduce memory usage

### Architecture

```
monte_carlo.py
├── MonteCarloSimulator (main engine)
│   ├── _generate_gbm_path() - Brownian motion
│   ├── _inject_black_swan() - Crash events
│   ├── _generate_correlated_shocks() - Multi-asset correlation
│   ├── _simulate_strategy_execution() - Day-by-day trading
│   ├── _calculate_path_metrics() - Per-path statistics
│   └── _calculate_risk_metrics() - Aggregate analysis
│
├── SimulationParameters (config)
├── SimulationPath (single path data)
└── RiskMetrics (results)
```

### Integration with Strategies

Any strategy inheriting from `BaseStrategy` can be stress-tested:

```python
from functions.strategies.base_strategy import BaseStrategy, TradingSignal

class MyStrategy(BaseStrategy):
    def evaluate(self, market_data, account_snapshot, regime):
        # Strategy logic
        return TradingSignal(...)

# Stress test it
simulator = MonteCarloSimulator()
paths, metrics = simulator.simulate_strategy(
    strategy_evaluate_fn=MyStrategy().evaluate
)
```

### Best Practices

1. **Always stress test before live trading**
2. **Run at least 1,000 simulations** for statistical significance
3. **Increase Black Swan probability** (20%+) for conservative testing
4. **Test across multiple market regimes** (bull, bear, sideways)
5. **Iterate on strategy parameters** until passing criteria
6. **Re-test monthly** as market conditions change

### References

- Geometric Brownian Motion: Black-Scholes-Merton model
- Value at Risk: Basel III regulatory framework
- Correlation Convergence: 2008 Financial Crisis analysis
- Sharpe Ratio: William F. Sharpe (1966)

### Support

For questions or issues:
- Check `scripts/run_stress_test.py` for examples
- Review `tests/test_monte_carlo.py` for unit tests
- See `IMPLEMENTATION_SUMMARY.md` for architecture details

## vNEXT: repo-wide non-invasive confirmation

A repo-wide scan shows **no vNEXT-labeled runtime code** (outside vendored dependencies), so vNEXT introduces:
- no imports from live-trading execution code
- no side effects
- no background threads
- no network calls
