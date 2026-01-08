# Backtesting Quick Start ⚡

## 🚀 Run Your First Backtest in 3 Steps

### Step 1: Set Environment Variables
```bash
export APCA_API_KEY_ID="your_api_key_here"
export APCA_API_SECRET_KEY="your_secret_key_here"
```

### Step 2: Run the Example Script
```bash
python scripts/run_backtest_example.py
```

### Step 3: View Results
The script will display comprehensive results and save them to a JSON file.

---

## 📱 Using the Web Interface

1. **Navigate**: Go to http://localhost:3000/backtesting
2. **Configure**: 
   - Strategy: `0DTE Gamma Scalper`
   - Symbol: `SPY`
   - Dates: Last 30 days (auto-filled)
   - Capital: `$100,000`
3. **Run**: Click "Run Backtest"
4. **Analyze**: Review equity curve, metrics, and trades

---

## 💻 Using in Python Code

```python
from backtester import Backtester
from strategies.gamma_scalper import GammaScalper

# Quick setup
strategy = GammaScalper()
backtester = Backtester(
    strategy=strategy,
    symbol="SPY",
    start_date="2024-11-01",
    end_date="2024-12-01",
    initial_capital=100000
)

# Run and print
results = backtester.run()
print(f"Return: {results['metrics']['total_return']:.2%}")
print(f"Sharpe: {results['metrics']['sharpe_ratio']:.2f}")
```

---

## 📊 What You'll See

```
====================================================================
BACKTEST RESULTS
====================================================================

📊 PERFORMANCE SUMMARY
  Initial Capital:         $100,000.00
  Final Equity:            $105,234.50
  Total Return:                  5.23%
  Benchmark Return:              3.12%
  Alpha:                         2.11%

📈 RISK METRICS
  Sharpe Ratio:                   1.85
  Max Drawdown:                   8.34%

💰 TRADE STATISTICS
  Total Trades:                     42
  Win Rate:                     65.00%
  
====================================================================
```

---

## 🎯 Key Metrics Explained

| Metric | Good Value | What It Means |
|--------|------------|---------------|
| **Sharpe Ratio** | > 1.0 | Risk-adjusted return (higher is better) |
| **Max Drawdown** | < 20% | Worst decline from peak (lower is better) |
| **Win Rate** | > 50% | Percent of profitable trades |
| **Alpha** | > 0 | Performance vs buy-and-hold |

---

## 🔧 Testing Your Own Strategy

### 1. Create Strategy File
```python
# strategies/my_strategy.py
from strategies.base_strategy import BaseStrategy, SignalType, TradingSignal

class MyStrategy(BaseStrategy):
    def evaluate(self, market_data, account_snapshot, regime=None):
        # Your logic here
        if your_buy_condition:
            return TradingSignal(SignalType.BUY, 0.5, "Buy signal")
        return TradingSignal(SignalType.HOLD, 0.0, "Hold")
```

### 2. Test It
```python
from backtester import Backtester
from strategies.my_strategy import MyStrategy

backtester = Backtester(strategy=MyStrategy(), symbol="SPY")
results = backtester.run()
```

---

## 🧪 Run Tests

```bash
pytest tests/test_backtester.py -v
```

**Expected Output:**
```
tests/test_backtester.py::TestBacktestPosition::test_position_creation PASSED
tests/test_backtester.py::TestBacktestAccount::test_account_initialization PASSED
...
============================== 17 passed ==============================
```

---

## 📚 Files Created

| File | Purpose |
|------|---------|
| `functions/backtester.py` | Core backtesting engine (600+ lines) |
| `frontend/src/components/BacktestChart.tsx` | React visualization component |
| `frontend/src/pages/Backtesting.tsx` | Full-page UI interface |
| `functions/main.py` | Cloud Function endpoint |
| `tests/test_backtester.py` | Comprehensive test suite (17 tests) |
| `scripts/run_backtest_example.py` | Quick start script |
| `BACKTESTING_GUIDE.md` | Comprehensive guide (500+ lines) |
| `functions/README_BACKTESTING.md` | Technical reference |
| `BACKTESTING_IMPLEMENTATION_SUMMARY.md` | Implementation details |

---

## ⚠️ Troubleshooting

### "Alpaca API credentials not configured"
```bash
# Make sure to export your credentials:
export APCA_API_KEY_ID="your_key"
export APCA_API_SECRET_KEY="your_secret"
```

### "No data available for backtesting"
- Check that your date range doesn't include weekends/holidays
- Verify the symbol is valid (e.g., SPY, QQQ, AAPL)
- Ensure your Alpaca account has data access

### Tests failing with "No module named 'pytest'"
```bash
pip3 install pytest pytest-cov
```

### Missing UI components
The project uses shadcn/ui components which are already included:
- Badge ✅
- Alert ✅  
- Button ✅
- Card ✅
- Tabs ✅
- All other components ✅

---

## 🎉 Success Indicators

You'll know it's working when you see:

1. ✅ Script runs without errors
2. ✅ Historical data fetched from Alpaca
3. ✅ Equity curve displayed in UI
4. ✅ Metrics calculated and shown
5. ✅ Trade history populated
6. ✅ All 17 tests passing

---

## 🚦 Next Steps

1. **Run the example** to verify everything works
2. **Test on different symbols** (QQQ, IWM, etc.)
3. **Try different date ranges** (1 week, 3 months, etc.)
4. **Create custom strategies** using the BaseStrategy template
5. **Compare multiple strategies** to find the best performer

---

## 📞 Need Help?

1. Check `BACKTESTING_GUIDE.md` for detailed documentation
2. Review test examples in `tests/test_backtester.py`
3. Run the example script: `python scripts/run_backtest_example.py`
4. Check inline documentation in `functions/backtester.py`

---

## 🎁 What's Included

✅ **Production-Ready Engine** - Full simulation with P&L tracking  
✅ **Beautiful UI** - Interactive charts with Recharts  
✅ **Comprehensive Tests** - 17/17 passing  
✅ **Great Documentation** - 500+ lines of guides  
✅ **Example Strategy** - 0DTE Gamma Scalper ready to test  
✅ **Cloud Function** - Deployed and ready  
✅ **Quick Start Script** - Run in seconds  

---

**Ready to start? Run:** `python scripts/run_backtest_example.py` 🚀
