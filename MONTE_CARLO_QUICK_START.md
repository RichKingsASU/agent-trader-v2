# Monte Carlo Stress Test - Quick Start Guide

## 🚀 Run Your First Stress Test in 3 Minutes

### Option 1: Python Script (Recommended for testing)

```bash
# 1. Navigate to project root
cd /workspace

# 2. Run the stress test
python scripts/run_stress_test.py
```

**Expected Output:**
```
================================================================================
MONTE CARLO STRESS TEST - Sector Rotation Strategy
================================================================================

Simulation Configuration:
  Strategy: Sector Rotation
  Simulations: 1000
  Trading Days: 252
  Initial Capital: $100,000
  Black Swan Probability: 10.0%

Running stress test...
Completed 100/1000 simulations
Completed 200/1000 simulations
...
Completed 1000/1000 simulations

================================================================================
STRESS TEST RESULTS
================================================================================

✅ STATUS: PASSED
The strategy meets all stress test criteria and is ready for live trading.

Value at Risk (95%): 12.30% (Limit: 15.00%) ✅
Survival Rate: 99.80% (Limit: 99.00%) ✅
Max Drawdown: 22.50% (Limit: 25.00%) ✅
Sharpe Ratio: 1.23 (Limit: 1.00) ✅

Full results saved to: stress_test_results.json
HTML report saved to: stress_test_report.html
```

**Time**: ~20 seconds for 1,000 simulations

---

### Option 2: UI Dashboard (Best for interactive use)

```bash
# 1. Start the backend
cd /workspace/backend
python -m uvicorn app:app --reload --port 8000

# 2. Start the frontend (in another terminal)
cd /workspace/frontend
npm run dev

# 3. Open browser
# Navigate to: http://localhost:5173/stress-test
```

**Steps in UI:**
1. Select strategy: "Sector Rotation"
2. Set simulations: 1000
3. Set trading days: 252
4. Click "Run Stress Test"
5. View results in real-time

**Features:**
- Interactive charts and graphs
- Risk metrics cards
- Pass/Fail status with interpretation
- Downloadable reports

---

### Option 3: API Endpoint (For programmatic use)

```bash
# Using curl
curl -X POST 'http://localhost:8000/api/analytics/stress-test?tenant_id=demo' \
  -H 'Content-Type: application/json' \
  -d '{
    "strategy_name": "sector_rotation",
    "num_simulations": 1000,
    "num_days": 252,
    "black_swan_probability": 0.10
  }'
```

**Using Python requests:**
```python
import requests

response = requests.post(
    'http://localhost:8000/api/analytics/stress-test?tenant_id=demo',
    json={
        'strategy_name': 'sector_rotation',
        'num_simulations': 1000,
        'num_days': 252,
        'black_swan_probability': 0.10
    }
)

results = response.json()
print(f"Pass: {results['passes_stress_test']}")
print(f"VaR(95%): {results['var_95']:.2%}")
```

**Using TypeScript/JavaScript:**
```typescript
const response = await fetch(
  '/api/analytics/stress-test?tenant_id=demo',
  {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      strategy_name: 'sector_rotation',
      num_simulations: 1000,
      num_days: 252,
      black_swan_probability: 0.10,
    })
  }
);

const results = await response.json();
console.log(`Pass: ${results.passes_stress_test}`);
```

---

## 📊 Understanding the Results

### Pass/Fail Status

✅ **PASS** = Strategy is safe for live trading
❌ **FAIL** = Strategy needs refinement

### Key Metrics

| Metric | What It Means | Good Value |
|--------|---------------|------------|
| **VaR (95%)** | Max loss in worst 5% of scenarios | ≤ 15% |
| **CVaR (95%)** | Average loss in tail scenarios | ≤ 18% |
| **Survival Rate** | % of paths avoiding liquidation | ≥ 99% |
| **Sharpe Ratio** | Risk-adjusted returns | ≥ 1.0 |
| **Max Drawdown** | Worst peak-to-trough decline | ≤ 25% |

### Example Interpretations

**Scenario 1: Aggressive Strategy**
```
VaR(95%) = 22% ❌
Sharpe = 1.8 ✅
Max Drawdown = 35% ❌

❌ FAIL - Too much downside risk despite good Sharpe ratio
→ Reduce position sizes or add hedging
```

**Scenario 2: Conservative Strategy**
```
VaR(95%) = 8% ✅
Sharpe = 0.7 ❌
Max Drawdown = 12% ✅

❌ FAIL - Low risk but insufficient returns
→ Increase allocation to high-conviction trades
```

**Scenario 3: Balanced Strategy**
```
VaR(95%) = 12% ✅
Sharpe = 1.3 ✅
Max Drawdown = 20% ✅
Survival = 99.8% ✅

✅ PASS - Ready for live trading!
```

---

## 🔧 Customizing Your Test

### Modify Simulation Parameters

**Quick (100 simulations)**:
```python
simulation_params = {
    "num_simulations": 100,  # Fast feedback
    "num_days": 126,  # 6 months
}
```

**Standard (1,000 simulations)**:
```python
simulation_params = {
    "num_simulations": 1000,  # Good balance
    "num_days": 252,  # 1 year
}
```

**Production (5,000 simulations)**:
```python
simulation_params = {
    "num_simulations": 5000,  # High confidence
    "num_days": 504,  # 2 years
    "black_swan_probability": 0.20,  # Conservative
}
```

### Modify Strategy Parameters

```python
strategy_config = {
    "lookback_days": 30,  # Longer momentum period
    "num_top_sectors": 5,  # More diversification
    "crash_threshold": -0.03,  # Earlier crash detection
    "rebalance_frequency_days": 10,  # Less frequent rebalancing
}
```

### Modify Risk Thresholds

```python
simulation_params = {
    "max_var_95": 0.12,  # More conservative (12% vs 15%)
    "min_survival_rate": 0.995,  # Higher survival requirement
    "max_drawdown": 0.20,  # Tighter drawdown limit
    "min_sharpe": 1.2,  # Higher Sharpe requirement
}
```

---

## 🐛 Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'numpy'"

**Solution:**
```bash
pip install numpy
# Or if using conda:
conda install numpy
```

### Issue: "Strategy evaluation failed"

**Check:**
1. Strategy inherits from `BaseStrategy`
2. `evaluate()` method returns `TradingSignal`
3. Market data has required fields (`symbol`, `price`)

**Debug:**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Issue: Simulation is slow

**Options:**
1. Reduce `num_simulations` (try 100 first)
2. Reduce `num_days` (try 126 for 6 months)
3. Set `save_all_paths=False` to reduce memory
4. Use `multiprocessing` (future enhancement)

### Issue: All paths failing

**Check:**
- Transaction costs might be too high
- Strategy might not be generating signals
- Initial capital might be insufficient

**Add logging:**
```python
logger.setLevel(logging.DEBUG)
# Will show detailed path execution
```

---

## 📈 Next Steps

### 1. Test Your Own Strategy

```python
from functions.strategies.base_strategy import BaseStrategy, TradingSignal, SignalType

class MyStrategy(BaseStrategy):
    def evaluate(self, market_data, account_snapshot, regime):
        # Your strategy logic here
        return TradingSignal(
            signal_type=SignalType.BUY,
            confidence=0.8,
            reasoning="Example signal",
            metadata={"symbol": "SPY", "allocation": 0.5}
        )

# Stress test it
from functions.stress_test_runner import run_stress_test

results = run_stress_test(
    strategy_name="my_strategy",  # Register your strategy first
    simulation_params={"num_simulations": 100}
)
```

### 2. Compare Multiple Strategies

```python
strategies = ["sector_rotation", "gamma_scalper", "my_strategy"]

for strategy in strategies:
    results = run_stress_test(strategy_name=strategy)
    print(f"{strategy}: Sharpe={results['risk_metrics']['mean_sharpe']:.2f}")
```

### 3. Optimize Parameters

```python
# Grid search over parameters
for lookback in [10, 20, 30]:
    for num_sectors in [2, 3, 5]:
        config = {"lookback_days": lookback, "num_top_sectors": num_sectors}
        results = run_stress_test(strategy_config=config)
        if results['risk_metrics']['passes_stress_test']:
            print(f"✅ lookback={lookback}, sectors={num_sectors}")
```

### 4. Schedule Regular Testing

```bash
# Add to cron (runs weekly)
0 0 * * 0 cd /workspace && python scripts/run_stress_test.py
```

---

## 📚 Additional Resources

- **Full Documentation**: `MONTE_CARLO_STRESS_TEST_IMPLEMENTATION.md`
- **API Reference**: `functions/utils/README.md`
- **Strategy Guide**: `functions/strategies/README.md`
- **Example Strategies**: `functions/strategies/sector_rotation.py`

---

## 🎯 Stress Test Checklist

Before deploying a strategy to live trading:

- [ ] Run stress test with 1,000+ simulations
- [ ] Passes all 4 criteria (VaR, Survival, Drawdown, Sharpe)
- [ ] Test with 20% Black Swan probability (conservative)
- [ ] Test over 252+ trading days (1+ year)
- [ ] Review worst-case scenarios (p1, p5 percentiles)
- [ ] Check recovery time < 30 days
- [ ] Document assumptions and limitations
- [ ] Get approval from risk management
- [ ] Monitor live performance vs. simulations
- [ ] Re-test monthly as markets change

---

## 💡 Pro Tips

1. **Start Small**: Test with 100 simulations first, then scale to 1,000+
2. **Iterate Quickly**: Use the UI for rapid parameter testing
3. **Understand Failures**: Don't just tweak numbers to pass—fix the strategy
4. **Test Edge Cases**: Try 50% Black Swan probability to see worst-case
5. **Compare Baselines**: Test against buy-and-hold SPY as a benchmark
6. **Document Everything**: Save all test results and decisions
7. **Re-test Regularly**: Markets change, strategies decay
8. **Use Multiple Metrics**: Don't rely on just one (VaR isn't everything)
9. **Simulate Correlations**: Test how your strategy handles crashes
10. **Trust the Process**: If it fails stress tests, don't trade it live!

---

**Ready to start? Run your first test now:**

```bash
python scripts/run_stress_test.py
```

Good luck! 🚀
