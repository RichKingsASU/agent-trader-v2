# Dynamic Sector Rotation Strategy

## Overview

The **Sector Rotation Strategy** is an automated portfolio management system that adjusts capital allocation based on real-time sentiment scores aggregated at the sector level. It implements a systematic approach to rotate capital into high-conviction sectors while reducing exposure to weak or deteriorating sectors.

## Key Features

### 1. Sector-Level Sentiment Aggregation
- Aggregates sentiment scores from individual ticker symbols to sector-level metrics
- Covers 10 major market sectors (Technology, Finance, Healthcare, Consumer, Energy, Industrial, Communications, Utilities, Materials, Real Estate)
- Each sector is tracked through 8+ constituent tickers for robust signal generation

### 2. Diverging Scale Conviction Levels

The strategy uses a diverging color scale to classify sentiment and conviction:

| Score Range | Color Zone | Conviction Level | Action |
|-------------|-----------|------------------|--------|
| **> 0.6** | 🟢 **Green** | High Conviction | Full allocation (100%) |
| **0.35 to 0.6** | 🟢 **Green** | Bullish | Standard allocation (100%) |
| **-0.3 to 0.3** | ⚪ **Gray** | Neutral | Hold current positions (0% change) |
| **-0.4 to -0.3** | ⚪ **Gray** | Caution | Reduce position by 50% |
| **-0.5 to -0.4** | 🔴 **Red** | Danger | Defensive sell / Underweight -20% |
| **< -0.5** | 🔴 **Red** | Extreme Danger | Immediate liquidation |

### 3. Dynamic Portfolio Allocation

**Core Allocation Rules:**
- Distributes **60%** of available capital across the top **3 sectors** with bullish sentiment (> 0.35)
- Each top sector receives an equal share: 60% ÷ 3 = **20% per sector**
- Allocation is adjusted based on conviction level (High Conviction sectors may receive additional weight)

**Example Allocation:**
```
Technology:  Score 0.82 → 20% allocation (High Conviction Green)
Finance:     Score 0.50 → 20% allocation (Bullish Green)  
Healthcare:  Score 0.45 → 20% allocation (Bullish Green)
Total Long:  60% allocated, 40% cash reserve
```

### 4. Automatic Risk Management

#### Turnover Limit Guard
To prevent excessive trading costs and whipsaw:
- Rebalancing is **blocked** unless sector sentiment changes by more than **20%**
- Example: Technology sentiment must move from 0.80 to 0.60 (or 1.00) to trigger rebalance
- First allocation is always executed (no prior baseline)

#### Market Hedge Override
Protects capital during systemic market events:
- Monitors **SPY (S&P 500)** sentiment as a market-wide risk indicator
- If SPY sentiment drops below **-0.5**, triggers emergency hedge:
  - **Overrides all sector signals**
  - Moves **80%** of portfolio to **CASH** or **SHV** (Short-term Treasuries)
  - Resumes normal operation when SPY sentiment recovers above threshold

### 5. Danger Zone Exit Logic

For sectors with existing positions that fall into danger territory:
- **Danger Zone** (< -0.4): Generate defensive SELL signal, reduce exposure by 20%+
- **Extreme Danger** (< -0.5): Immediate SELL signal, liquidate 100% of sector positions
- Priority: Exit danger positions before allocating to new sectors

## Strategy Execution Rules Table

| Sector Score | Heatmap Color | Bot Action | Portfolio Impact |
|--------------|---------------|------------|------------------|
| **0.4 to 1.0** | 🟢 **Green** | Aggressive Buy | Overweight +20% Allocation |
| **-0.3 to 0.3** | ⚪ **Gray** | Hold / Neutral | Market Weight (No Change) |
| **-1.0 to -0.4** | 🔴 **Red** | Defensive Sell | Underweight -20% to Liquidate |

## Configuration Options

The strategy accepts the following configuration parameters:

```python
config = {
    'top_n_sectors': 3,          # Number of top sectors to allocate to (default: 3)
    'long_allocation': 0.60,     # Percentage of capital to allocate (default: 60%)
    'turnover_threshold': 0.20,  # Minimum sentiment change to rebalance (default: 20%)
    'spy_threshold': -0.5,       # SPY sentiment threshold for market hedge (default: -0.5)
    'cash_hedge_pct': 0.80,      # Percentage to move to cash on systemic risk (default: 80%)
    'enable_hedging': True,      # Enable/disable SPY hedge override (default: True)
}
```

## Usage Example

### 1. Instantiate the Strategy

```python
from strategies import StrategyLoader
from firebase_admin import firestore

# Initialize Firestore
db = firestore.client()

# Create strategy loader
loader = StrategyLoader(db=db, config={})

# Instantiate sector rotation strategy with custom config
config = {
    'top_n_sectors': 3,
    'long_allocation': 0.60,
    'enable_hedging': True,
}

from strategies.sector_rotation import SectorRotationStrategy
strategy = SectorRotationStrategy(name='my_sector_rotation', config=config)
```

### 2. Fetch Sentiment Data from Firestore

```python
# Fetch sentiment scores for all tickers
# Assumes Firestore structure: marketData/sentiment/sectors/{sector}/tickers/{ticker}

async def fetch_sentiment_scores(db: firestore.Client) -> dict:
    """Fetch sentiment scores from Firestore."""
    tickers_data = []
    
    # Query tradingSignals or marketData collection for latest sentiment
    signals_ref = db.collection('tradingSignals').order_by('timestamp', direction='DESCENDING').limit(100)
    signals = signals_ref.stream()
    
    for signal in signals:
        data = signal.to_dict()
        if 'sentiment_score' in data:
            tickers_data.append({
                'symbol': data.get('symbol', ''),
                'sentiment_score': data.get('sentiment_score', 0.0),
                'confidence': data.get('confidence', 0.0),
            })
    
    return {'tickers': tickers_data}
```

### 3. Evaluate Strategy

```python
# Get account snapshot (from Alpaca or Firestore)
account_snapshot = {
    'equity': '100000.00',
    'buying_power': '50000.00',
    'cash': '40000.00',
    'positions': [
        {'symbol': 'XLK', 'qty': '100', 'market_value': '15000.00'},
        {'symbol': 'XLE', 'qty': '50', 'market_value': '4000.00'},
    ]
}

# Fetch market data (sentiment scores)
market_data = await fetch_sentiment_scores(db)

# Evaluate strategy
signal = await strategy.evaluate(
    market_data=market_data,
    account_snapshot=account_snapshot,
    regime_data=None  # Optional GEX regime data
)

print(f"Action: {signal['action']}")
print(f"Ticker: {signal['ticker']}")
print(f"Allocation: {signal['allocation']:.1%}")
print(f"Reasoning: {signal['reasoning']}")
```

### 4. Expected Signal Output

```python
{
    'action': 'BUY',
    'allocation': 0.20,  # 20% of capital
    'ticker': 'XLK',     # Technology Sector ETF
    'reasoning': '''
        SECTOR ROTATION: Allocating 60.0% of capital to top 3 sectors based on sentiment analysis:
        
          1. Technology: Sentiment 0.82 (High Conviction Green) → Allocation: 20.0%
          2. Finance: Sentiment 0.50 (Bullish Green) → Allocation: 20.0%
          3. Healthcare: Sentiment 0.45 (Bullish Green) → Allocation: 20.0%
        
        Rationale:
          • Overweighting Technology due to high conviction (sentiment 0.82 > 0.6)
          • Bullish on Finance with sentiment 0.50 (above threshold 0.35)
          • Bullish on Healthcare with sentiment 0.45 (above threshold 0.35)
        
        Market Overview: Average sector sentiment: 0.42
    ''',
    'metadata': {
        'timestamp': '2025-12-30T12:00:00Z',
        'strategy': 'sector_rotation',
        'sector': 'Technology',
        'sentiment_score': 0.82,
        'conviction_level': 'High Conviction (Green)',
        'signal_type': 'sector_rotation',
        'top_sectors': [
            ('Technology', 0.82),
            ('Finance', 0.50),
            ('Healthcare', 0.45),
        ],
        'sector_scores': {
            'Technology': 0.82,
            'Finance': 0.50,
            'Healthcare': 0.45,
            'Energy': -0.45,
            'Consumer': 0.38,
            # ... other sectors
        }
    }
}
```

## Sector Definitions

The strategy tracks 10 major market sectors with their constituent tickers and ETF mappings:

### Sector Constituents

| Sector | Constituent Tickers | Sector ETF |
|--------|---------------------|------------|
| **Technology** | AAPL, MSFT, GOOGL, NVDA, META, AMD, CRM, ADBE | XLK |
| **Finance** | JPM, BAC, GS, MS, WFC, C, BLK, SCHW | XLF |
| **Healthcare** | UNH, JNJ, LLY, PFE, ABBV, TMO, MRK, ABT | XLV |
| **Consumer** | AMZN, TSLA, HD, MCD, NKE, SBUX, TGT, LOW | XLY |
| **Energy** | XOM, CVX, COP, SLB, EOG, MPC, PSX, VLO | XLE |
| **Industrial** | BA, CAT, GE, HON, UNP, UPS, LMT, RTX | XLI |
| **Communications** | GOOG, META, DIS, NFLX, CMCSA, VZ, T | XLC |
| **Utilities** | NEE, DUK, SO, D, AEP, EXC, SRE, XEL | XLU |
| **Materials** | LIN, APD, SHW, FCX, NEM, DOW, DD, NUE | XLB |
| **Real Estate** | AMT, PLD, CCI, EQIX, PSA, SPG, O, WELL | XLRE |

## Integration with Sentiment Heatmap

The strategy is designed to work seamlessly with the existing **Sentiment Heatmap** system:

1. **Data Source**: Fetches sentiment scores from Firestore `tradingSignals` or `marketData/sentiment` collections
2. **Real-time Updates**: Automatically updates as new sentiment analyses are generated by Gemini 1.5 Flash
3. **Visual Feedback**: Strategy reasoning uses the same color scale (Green/Gray/Red) as the heatmap for consistency

## Safety Features

### 1. Turnover Protection
- Prevents excessive rebalancing (commission costs)
- Requires 20% sentiment deviation to trigger rebalance
- Tracks previous sector scores to calculate deviation

### 2. Market Hedge Override
- Monitors SPY for systemic market risk
- Automatic emergency hedge to cash/treasuries
- Overrides all sector signals during crisis

### 3. Position-Aware Risk Management
- Prioritizes exiting danger sectors with existing positions
- Avoids allocating to neutral/weak sectors
- Maintains 40% cash reserve for flexibility

### 4. Comprehensive Reasoning
Every signal includes detailed reasoning explaining:
- Which sectors are being allocated to and why
- Sentiment scores and conviction levels
- Market context (average sentiment)
- Risk factors (SPY sentiment, danger sectors)

## Testing

The strategy includes a comprehensive test suite covering:

- **Helper Methods**: Sentiment aggregation, sector selection, conviction classification
- **Turnover Limits**: First rebalance, blocked rebalances, allowed rebalances
- **Signal Generation**: Bullish signals, danger exits, systemic hedge, reasoning quality
- **Edge Cases**: No data, no bullish sectors, partial data, hedging disabled
- **Configuration**: Custom parameters, allocation percentages, thresholds
- **Integration**: Full rotation cycles, multi-sector allocation

Run tests:
```bash
cd /workspace/functions/strategies
pytest test_sector_rotation.py -v
```

## Deployment

### 1. Register Strategy in Firestore

Add strategy definition to `strategies` collection:

```python
from firebase_admin import firestore

db = firestore.client()

strategy_doc = {
    'name': 'sector_rotation',
    'display_name': 'Dynamic Sector Rotation',
    'description': 'Automated sector rotation based on real-time sentiment scores',
    'class_name': 'SectorRotationStrategy',
    'module_path': 'functions.strategies.sector_rotation',
    'config': {
        'top_n_sectors': 3,
        'long_allocation': 0.60,
        'turnover_threshold': 0.20,
        'spy_threshold': -0.5,
        'enable_hedging': True,
    },
    'enabled': True,
    'created_at': firestore.SERVER_TIMESTAMP,
}

db.collection('strategies').document('sector_rotation').set(strategy_doc)
```

### 2. Deploy to Cloud Functions

The strategy is automatically discovered by the `StrategyLoader` when deployed:

```bash
cd /workspace
firebase deploy --only functions
```

### 3. Schedule Execution

Set up Cloud Scheduler to run the strategy:

```bash
gcloud scheduler jobs create http sector-rotation-strategy \
  --schedule="0 9,12,15 * * 1-5" \
  --uri="https://us-central1-your-project.cloudfunctions.net/strategy_engine" \
  --http-method=POST \
  --message-body='{"strategy":"sector_rotation"}' \
  --time-zone="America/New_York"
```

## Performance Considerations

### Execution Frequency
- **Recommended**: Run 3x per trading day (9 AM, 12 PM, 3 PM ET)
- **Minimum**: Daily (pre-market)
- **Maximum**: Every 30 minutes (may incur higher costs)

### Firestore Reads
- ~100 reads per evaluation (sentiment scores for all tickers)
- Cost: ~$0.036 per 100,000 reads
- Daily cost (3x/day): negligible

### Vertex AI Costs
- Strategy itself doesn't call Vertex AI (uses pre-computed sentiment scores)
- Sentiment analysis costs are in the heatmap/sentiment engine

## Monitoring & Alerting

### Key Metrics to Track

1. **Sector Score Deviation**: Track max deviation between rebalances
2. **Turnover Rate**: How often rebalancing occurs
3. **SPY Sentiment**: Monitor for systemic risk events
4. **Allocation Distribution**: Verify 60% allocation target is met
5. **Danger Zone Exits**: Track how often positions are liquidated

### Firestore Logging

All signals are logged to `tradingSignals` collection with full metadata:
- Timestamp
- Strategy name
- Action (BUY/SELL/HOLD)
- Ticker symbol
- Allocation percentage
- Reasoning
- Sector scores
- Top sectors
- Danger sectors

## Troubleshooting

### Problem: Strategy always returns HOLD

**Cause**: Turnover limit is blocking rebalancing

**Solution**: 
- Check `last_sector_scores` state
- Verify sentiment changes exceed 20% threshold
- Consider lowering `turnover_threshold` in config

### Problem: No sectors selected for allocation

**Cause**: All sectors below bullish threshold (0.35)

**Solution**:
- Review sentiment data quality
- Check if market is broadly negative
- Consider lowering `ConvictionThresholds.BULLISH` in code

### Problem: SPY hedge triggers too often

**Cause**: SPY threshold too high (-0.5)

**Solution**:
- Lower `spy_threshold` to -0.6 or -0.7 for less sensitivity
- Or disable hedging: `enable_hedging: False`

## Future Enhancements

Potential improvements for future versions:

1. **Dynamic N Selection**: Adjust `top_n_sectors` based on market breadth
2. **Confidence Weighting**: Weight sector allocation by confidence scores
3. **Multi-Timeframe Analysis**: Consider sentiment trends over 1d, 1w, 1m
4. **Sector Correlation**: Avoid over-concentration in correlated sectors
5. **Options Hedging**: Use sector put options for downside protection
6. **Backtesting Framework**: Historical performance analysis
7. **Real-time Execution**: Integrate with Alpaca API for automatic trade execution

## License

Copyright © 2025. All rights reserved.

## Support

For questions or issues, please contact the development team or file an issue in the repository.

---

**Last Updated**: December 30, 2025  
**Version**: 1.0.0  
**Author**: AI Strategy Engineering Team
