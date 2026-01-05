# Sector Rotation Strategy - Quick Start Guide

## 🚀 Implementation Complete!

The **Dynamic Sector Rotation Strategy** has been successfully implemented and is ready to use. This guide will help you get started quickly.

## 📁 Files Created

| File | Purpose |
|------|---------|
| `functions/strategies/sector_rotation.py` | Main strategy implementation |
| `functions/strategies/test_sector_rotation.py` | Comprehensive test suite |
| `functions/strategies/verify_sector_rotation_loader.py` | Loader verification script |
| `functions/strategies/SECTOR_ROTATION_README.md` | Detailed documentation |
| `scripts/run_sector_rotation_strategy.py` | Command-line runner script |
| `SECTOR_ROTATION_QUICK_START.md` | This guide |

## ✅ Verification Status

The strategy has been verified and is **READY TO USE**:

- ✅ Strategy class implemented with all required features
- ✅ Properly inherits from `BaseStrategy`
- ✅ Discovered automatically by `StrategyLoader`
- ✅ Test suite created (35+ test cases)
- ✅ Documentation completed
- ✅ Example runner script created

**Verification Output:**
```
✓ Found 3 strategies: SectorRotationStrategy, AnotherExampleStrategy, ExampleStrategy
✓ SectorRotationStrategy is loaded
✓ Strategy evaluation completed successfully
✓ All verification checks passed!
```

## 🎯 Strategy Features

### Core Functionality
- ✅ **Sector-level sentiment aggregation** from 50+ individual tickers across 10 sectors
- ✅ **Dynamic allocation** - 60% to top 3 bullish sectors
- ✅ **Diverging scale conviction levels** - Green/Gray/Red zones
- ✅ **Turnover protection** - 20% threshold prevents excessive rebalancing
- ✅ **SPY hedge override** - Automatic cash allocation on systemic risk
- ✅ **Position-aware risk management** - Prioritizes danger zone exits
- ✅ **Comprehensive reasoning** - Every signal includes detailed explanation

### Strategy Execution Rules

| Sector Score | Heatmap Color | Bot Action | Portfolio Impact |
|--------------|---------------|------------|------------------|
| **0.4 to 1.0** | 🟢 **Green** | Aggressive Buy | Overweight +20% Allocation |
| **-0.3 to 0.3** | ⚪ **Gray** | Hold / Neutral | Market Weight (No Change) |
| **-1.0 to -0.4** | 🔴 **Red** | Defensive Sell | Underweight -20% to Liquidate |

## 🏃 Quick Start: Run the Strategy

### Option 1: Dry Run (Recommended First)

```bash
cd /workspace
python3 scripts/run_sector_rotation_strategy.py
```

This will:
1. Fetch sentiment scores from Firestore
2. Fetch account snapshot
3. Evaluate the strategy
4. Display the signal and reasoning
5. **NOT execute** any trades (dry run mode)

### Option 2: Execute Trades (Production)

```bash
python3 scripts/run_sector_rotation_strategy.py --execute
```

**⚠️ Warning:** This will actually place trades via your Alpaca account!

### Option 3: Custom Configuration

```bash
# Allocate to top 5 sectors instead of 3
python3 scripts/run_sector_rotation_strategy.py --top-n 5 --allocation 0.70

# Disable market hedging
python3 scripts/run_sector_rotation_strategy.py --no-hedging

# Use specific tenant
python3 scripts/run_sector_rotation_strategy.py --tenant-id your-tenant-id
```

## 📊 Example Output

When you run the strategy, you'll see output like this:

```
================================================================================
Dynamic Sector Rotation Strategy - Execution
================================================================================
Configuration:
  Top N Sectors:       3
  Long Allocation:     60.0%
  Turnover Threshold:  20.0%
  SPY Threshold:       -0.5
  Enable Hedging:      True
  Execute Trades:      False
================================================================================

Fetching sentiment data from Firestore...
Fetched sentiment data for 42 tickers

Account snapshot loaded: equity=$100,000.00

Evaluating strategy...
Strategy evaluation completed

================================================================================
STRATEGY SIGNAL
================================================================================
Action:      BUY
Ticker:      XLK
Allocation:  20.0%

Reasoning:
--------------------------------------------------------------------------------
SECTOR ROTATION: Allocating 60.0% of capital to top 3 sectors based on sentiment analysis:

  1. Technology: Sentiment 0.75 (High Conviction Green) → Allocation: 20.0%
  2. Healthcare: Sentiment 0.47 (Bullish Green) → Allocation: 20.0%
  3. Finance: Sentiment 0.38 (Bullish Green) → Allocation: 20.0%

Rationale:
  • Overweighting Technology due to high conviction (sentiment 0.75 > 0.6)
  • Bullish on Healthcare with sentiment 0.47 (above threshold 0.35)
  • Bullish on Finance with sentiment 0.38 (above threshold 0.35)

Market Overview: Average sector sentiment: 0.53
--------------------------------------------------------------------------------

Sector Scores:
--------------------------------------------------------------------------------
  🟢 Technology            +0.750
  🟢 Healthcare            +0.475
  🟢 Finance               +0.375
  ⚪ Consumer              +0.200
  ⚪ Communications        +0.150
  ⚪ Utilities             +0.050
  🔴 Energy                -0.420
  🔴 Industrial            -0.380
  🔴 Materials             -0.550
  🔴 RealEstate            -0.600
--------------------------------------------------------------------------------

Signal saved to Firestore: tradingSignals/abc123xyz
ℹ Dry run mode - no trade executed

================================================================================
Strategy execution completed
================================================================================
```

## 🧪 Run Tests

The strategy includes a comprehensive test suite:

```bash
cd /workspace/functions/strategies

# Run all tests
pytest test_sector_rotation.py -v

# Run specific test class
pytest test_sector_rotation.py::TestSignalGeneration -v

# Run with coverage
pytest test_sector_rotation.py --cov=sector_rotation --cov-report=html
```

**Test Coverage:**
- ✅ Helper methods (sentiment aggregation, conviction levels)
- ✅ Turnover limits (first rebalance, blocked, allowed)
- ✅ Signal generation (bullish, bearish, danger exits, hedge)
- ✅ Edge cases (no data, partial data, extreme conditions)
- ✅ Configuration (custom parameters)
- ✅ Integration (full rotation cycles)

## 🔧 Configuration Options

You can customize the strategy behavior via config parameters:

```python
config = {
    'top_n_sectors': 3,          # Number of sectors to allocate to (default: 3)
    'long_allocation': 0.60,     # Percentage of capital (default: 60%)
    'turnover_threshold': 0.20,  # Rebalance threshold (default: 20%)
    'spy_threshold': -0.5,       # SPY hedge threshold (default: -0.5)
    'cash_hedge_pct': 0.80,      # Cash allocation on hedge (default: 80%)
    'enable_hedging': True,      # Enable SPY override (default: True)
}
```

## 📈 Integration with Existing Systems

### 1. Sentiment Heatmap Integration

The strategy uses the same sentiment data as your existing **Sentiment Heatmap**:

- **Data Source**: `tradingSignals` collection in Firestore
- **Sentiment Engine**: Gemini 1.5 Flash AI analysis
- **Update Frequency**: Real-time as new analyses are generated
- **Color Scale**: Same Green/Gray/Red zones

### 2. Strategy Loader Integration

The strategy is automatically discovered by the `StrategyLoader`:

```python
from strategies import get_strategy_loader

loader = get_strategy_loader()
strategy = loader.get_strategy('SectorRotationStrategy')
```

### 3. Firestore Integration

Signals are automatically written to `tradingSignals` collection:

```javascript
// Firestore document structure
tradingSignals/{doc_id} = {
  strategy: 'sector_rotation',
  strategy_name: 'Dynamic Sector Rotation',
  timestamp: '2025-12-30T12:00:00Z',
  action: 'BUY',
  ticker: 'XLK',
  allocation: 0.20,
  reasoning: '...',
  metadata: {
    sector: 'Technology',
    sentiment_score: 0.82,
    conviction_level: 'High Conviction (Green)',
    sector_scores: {...},
    top_sectors: [...]
  }
}
```

## 🔄 Deployment

### Cloud Functions Deployment

The strategy is ready for Cloud Functions deployment:

```bash
cd /workspace
firebase deploy --only functions
```

### Cloud Scheduler Setup

Schedule the strategy to run automatically:

```bash
# Run 3x per trading day (9 AM, 12 PM, 3 PM ET)
gcloud scheduler jobs create http sector-rotation-strategy \
  --schedule="0 9,12,15 * * 1-5" \
  --uri="https://us-central1-YOUR-PROJECT.cloudfunctions.net/strategy_engine" \
  --http-method=POST \
  --message-body='{"strategy":"sector_rotation"}' \
  --time-zone="America/New_York"
```

### Firestore Strategy Registration

Register the strategy in your `strategies` collection:

```python
import firebase_admin
from firebase_admin import firestore

db = firestore.client()

strategy_doc = {
    'name': 'sector_rotation',
    'display_name': 'Dynamic Sector Rotation',
    'description': 'Automated sector rotation based on real-time sentiment scores',
    'class_name': 'SectorRotationStrategy',
    'module_path': 'functions.strategies.sector_rotation',
    'enabled': True,
    'config': {
        'top_n_sectors': 3,
        'long_allocation': 0.60,
        'turnover_threshold': 0.20,
    },
    'created_at': firestore.SERVER_TIMESTAMP,
}

db.collection('strategies').document('sector_rotation').set(strategy_doc)
```

## 📋 Sector Definitions

The strategy tracks **10 major market sectors**:

| Sector | ETF | Sample Constituents |
|--------|-----|---------------------|
| Technology | XLK | AAPL, MSFT, NVDA, GOOGL |
| Finance | XLF | JPM, BAC, GS, MS |
| Healthcare | XLV | UNH, JNJ, LLY, PFE |
| Consumer | XLY | AMZN, TSLA, HD, MCD |
| Energy | XLE | XOM, CVX, COP, SLB |
| Industrial | XLI | BA, CAT, GE, HON |
| Communications | XLC | GOOG, META, DIS, NFLX |
| Utilities | XLU | NEE, DUK, SO, D |
| Materials | XLB | LIN, APD, SHW, FCX |
| Real Estate | XLRE | AMT, PLD, CCI, EQIX |

Each sector is tracked through **8+ constituent tickers** for robust sentiment aggregation.

## 🎨 Conviction Levels & Color Zones

The strategy uses a **diverging color scale** to classify sentiment:

### 🟢 Green Zone (Bullish)
- **High Conviction** (> 0.6): Full allocation, overweight
- **Bullish** (0.35 to 0.6): Standard allocation

### ⚪ Gray Zone (Neutral)
- **Neutral** (-0.3 to 0.3): Hold current positions, no change
- **Caution** (-0.2 to -0.3): Reduce position by 50%

### 🔴 Red Zone (Bearish)
- **Danger** (-0.4 to -0.5): Defensive sell, underweight -20%
- **Extreme Danger** (< -0.5): Immediate liquidation

## 🛡️ Safety Features

### 1. Turnover Protection
- Blocks rebalancing unless sentiment changes > 20%
- Prevents excessive trading costs
- Avoids whipsaw in choppy markets

### 2. Market Hedge Override
- Monitors SPY for systemic risk
- Automatic move to 80% cash/SHV when SPY < -0.5
- Overrides all sector signals during crisis

### 3. Position-Aware Risk Management
- Prioritizes exiting danger sectors with existing positions
- Won't allocate to neutral/weak sectors
- Maintains 40% cash reserve for flexibility

## 📚 Additional Resources

- **Full Documentation**: `functions/strategies/SECTOR_ROTATION_README.md`
- **Test Suite**: `functions/strategies/test_sector_rotation.py`
- **Strategy Code**: `functions/strategies/sector_rotation.py`
- **Runner Script**: `scripts/run_sector_rotation_strategy.py`

## 🐛 Troubleshooting

### Issue: No sentiment data available

**Solution:** Run sentiment analysis to generate scores:
```bash
python3 -m backend.strategy_engine.sentiment_strategy_driver
```

### Issue: Strategy always returns HOLD

**Cause:** Turnover limit is blocking rebalancing

**Solution:** Lower `turnover_threshold` in config or wait for larger sentiment changes

### Issue: SPY hedge triggers too frequently

**Solution:** Lower `spy_threshold` to -0.6 or disable: `--no-hedging`

## 🎉 Next Steps

1. **Test in dry run mode** to verify behavior
2. **Review sentiment data** quality and coverage
3. **Adjust configuration** based on risk tolerance
4. **Deploy to Cloud Functions** for automated execution
5. **Set up Cloud Scheduler** for periodic runs
6. **Monitor performance** via Firestore signals

## 📞 Support

For questions or issues:
- Review the detailed README: `functions/strategies/SECTOR_ROTATION_README.md`
- Check test cases: `functions/strategies/test_sector_rotation.py`
- Inspect strategy code: `functions/strategies/sector_rotation.py`

---

**Strategy Version**: 1.0.0  
**Date**: December 30, 2025  
**Status**: ✅ Production Ready

**Happy Trading! 🚀📈**
