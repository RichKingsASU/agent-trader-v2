# Historical Backtester - Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Step 1: Navigate to Backtest Lab
Open your application and click **"Backtest Lab"** in the sidebar under the Development section, or navigate to:
```
http://localhost:5173/backtest
```

### Step 2: Configure Your Backtest

**Basic Configuration**:
- **Strategy**: Select "GammaScalper" (0DTE options strategy)
- **Symbol**: Enter "SPY"
- **Lookback Days**: 30 days
- **Starting Capital**: $100,000
- **Slippage**: 1 basis point (0.01%)

**Optional**:
- **Market Regime**: Leave as "Auto-detect" or select LONG_GAMMA/SHORT_GAMMA

### Step 3: Run the Backtest

Click the **"Run Backtest"** button and wait ~10-30 seconds while the system:
1. Fetches 30 days of 1-minute SPY bars from Alpaca
2. Simulates your strategy on historical data
3. Calculates performance metrics
4. Generates equity curve and trade analysis

### Step 4: Review Results

#### Equity Curve Tab
- **Blue line**: Your portfolio value over time
- **Dashed line**: Starting capital benchmark
- **Interpretation**: Line going up = profit, going down = loss

#### Performance Metrics Tab
- **Total Return**: Overall profit/loss percentage
- **Sharpe Ratio**: Risk-adjusted return (>1.0 is good, >2.0 is excellent)
- **Max Drawdown**: Worst peak-to-trough loss
- **Win Rate**: Percentage of profitable trades

#### Trade Analysis Tab
- **Total Trades**: Number of buy/sell pairs
- **Win Rate**: How often you made money
- **Avg Win/Loss**: Average profit per winning trade vs. average loss per losing trade
- **Profit Factor**: Gross profit ÷ gross loss (>1.5 is good)

## 📊 Understanding Your Results

### Good Performance Indicators
✅ **Total Return** > 10% (monthly) or > 50% (annual)  
✅ **Sharpe Ratio** > 1.5  
✅ **Win Rate** > 55%  
✅ **Max Drawdown** < 15%  
✅ **Profit Factor** > 1.5  

### Warning Signs
⚠️ **Total Return** < 0% (losing money)  
⚠️ **Sharpe Ratio** < 0.5 (poor risk-adjusted returns)  
⚠️ **Win Rate** < 40% (losing more often than winning)  
⚠️ **Max Drawdown** > 30% (excessive risk)  
⚠️ **Profit Factor** < 1.0 (losing more than gaining)  

## 🎯 Example Strategies to Try

### 1. Gamma Scalper (0DTE Options)
```
Strategy: GammaScalper
Symbol: SPY
Config: { threshold: 0.15 }
Lookback: 30 days
Capital: $100,000
```
**Expected**: Medium-frequency trading, targets small gains from delta hedging

### 2. Delta Momentum
```
Strategy: DeltaMomentumStrategy
Symbol: QQQ
Config: { threshold: 0.20 }
Lookback: 30 days
Capital: $100,000
```
**Expected**: Momentum-based entries, higher win rate but fewer trades

### 3. Congressional Alpha
```
Strategy: CongressionalAlphaStrategy
Symbol: SPY
Config: {}
Lookback: 60 days
Capital: $50,000
```
**Expected**: Low-frequency trading, follows congressional trading signals

## 🔬 Experiment with Parameters

### Test Different Lookback Periods
- **5 days**: Quick test, high variance
- **30 days**: Balanced, typical backtest
- **90 days**: Longer-term, more stable metrics
- **180+ days**: Comprehensive analysis

### Test Different Market Regimes
- **Auto-detect**: Let the system determine regime from data
- **LONG_GAMMA**: Test in stabilizing markets (low volatility)
- **SHORT_GAMMA**: Test in volatile markets (high volatility)
- **NEUTRAL**: Test in neutral conditions

### Test Different Symbols
- **SPY**: S&P 500 ETF (most liquid, safest)
- **QQQ**: Nasdaq ETF (tech-heavy, more volatile)
- **IWM**: Russell 2000 ETF (small caps, higher risk)
- **AAPL, MSFT, TSLA**: Individual stocks (higher risk, lower liquidity)

## 🎓 Tips for Better Backtesting

### 1. Start Small
Begin with 5-10 days to test quickly, then expand to 30-90 days for reliable metrics.

### 2. Compare Multiple Strategies
Run the same configuration on different strategies to see which performs best.

### 3. Test Different Market Conditions
- Run backtests on bull markets (2023)
- Run backtests on bear markets (2022)
- Run backtests on sideways markets (2015-2016)

### 4. Watch for Overfitting
If a strategy has:
- Win rate > 80%
- Sharpe ratio > 3.0
- No losing trades

...it might be overfitted or have look-ahead bias. Verify the strategy logic.

### 5. Consider Transaction Costs
The default 0.01% slippage is realistic for liquid ETFs like SPY. For less liquid symbols, increase to 0.05% (5 bps) or more.

## 🐛 Troubleshooting

### "Alpaca credentials not configured"
**Solution**: Go to Settings → API Keys and configure your Alpaca API credentials.

### "No historical data available"
**Solution**: 
- Check that the symbol is valid (e.g., "SPY", not "spy" or "S&P500")
- Reduce lookback days (Alpaca has limits on historical data)
- Check that markets were open during the selected period

### "Strategy not found"
**Solution**: 
- Use exact strategy name: "GammaScalper", not "Gamma Scalper" or "gamma_scalper"
- Check available strategies in the dropdown

### Results take too long
**Solution**:
- Reduce lookback days (30 days = ~12k bars, 90 days = ~36k bars)
- Use less frequent timeframes (future enhancement)

### Unrealistic results
**Check**:
- Slippage is set to at least 1 bps (0.01%)
- Lookback period includes various market conditions
- Strategy logic doesn't use future data

## 📚 Next Steps

1. **Run your first backtest** with default settings
2. **Experiment with parameters** (symbol, days, regime)
3. **Compare strategies** on the same data
4. **Analyze metrics** to understand performance
5. **Refine your strategy** based on results
6. **Test in different market conditions** (bull, bear, sideways)

## 🔗 Additional Resources

- **Implementation Summary**: `BACKTESTER_IMPLEMENTATION_SUMMARY.md`
- **Architecture Verification**: `BACKTESTER_ARCHITECTURE_VERIFICATION.md`
- **Strategy Development**: `functions/strategies/README.md`
- **BaseStrategy API**: `functions/strategies/base_strategy.py`

## 💡 Pro Tips

### Metric Interpretation

**Sharpe Ratio**:
- < 1.0: Poor (high risk, low return)
- 1.0 - 2.0: Good (balanced risk/return)
- 2.0 - 3.0: Excellent (low risk, high return)
- \> 3.0: Suspicious (check for errors)

**Max Drawdown**:
- < 10%: Conservative
- 10% - 20%: Moderate
- 20% - 30%: Aggressive
- \> 30%: Very risky

**Win Rate**:
- < 40%: Poor (need higher avg win vs avg loss)
- 40% - 55%: Average (typical for many strategies)
- 55% - 70%: Good (profitable with reasonable risk)
- \> 70%: Excellent (very consistent)

**Profit Factor**:
- < 1.0: Losing strategy (gross losses > gross profits)
- 1.0 - 1.5: Marginally profitable
- 1.5 - 2.5: Good (wins significantly outweigh losses)
- \> 2.5: Excellent (very profitable)

### Strategy Selection Guide

**For Beginners**:
Start with **GammaScalper** on **SPY** with **30 days**. It's well-tested and provides good baseline results.

**For Day Traders**:
Try **DeltaMomentumStrategy** on **QQQ** with **60 days**. It captures intraday momentum moves.

**For Swing Traders**:
Use **CongressionalAlphaStrategy** on **SPY** with **90 days**. It trades less frequently but captures larger moves.

## ✅ Quick Checklist

Before running your first backtest:
- [ ] Alpaca API keys configured in Settings
- [ ] Strategy selected from dropdown
- [ ] Symbol entered (e.g., SPY)
- [ ] Lookback days set (5-90 recommended)
- [ ] Starting capital set (e.g., $100,000)

After your backtest completes:
- [ ] Equity curve shows reasonable growth/decline
- [ ] Total return is not unrealistically high (>200% in 30 days)
- [ ] Sharpe ratio is between -2 and 3
- [ ] Trade count is > 0 (strategy actually traded)
- [ ] Max drawdown is < 50% (strategy manages risk)

---

**Need Help?** Check the troubleshooting section above or review the full implementation summary.

**Happy Backtesting! 🚀📈**
