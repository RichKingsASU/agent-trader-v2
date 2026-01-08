# LLM-Enhanced Sentiment Strategy

## Overview

The **LLM Sentiment Alpha** strategy implements a reasoning-driven approach to news sentiment analysis using Gemini 1.5 Flash. Unlike traditional sentiment scoring, this strategy asks the AI to deeply analyze the impact of news on future cash flows and business fundamentals.

## Strategy Components

### 1. News Ingestion
- **Source**: Alpaca News API
- **Data**: Real-time news headlines and summaries
- **Symbols**: Configurable via `STRATEGY_SYMBOLS` environment variable
- **Lookback**: Default 24 hours (configurable)

### 2. AI Analysis Engine
- **Model**: Gemini 1.5 Flash (via Vertex AI)
- **Analysis Type**: Reasoning-driven fundamental analysis
- **Focus Areas**:
  - Future cash flow impact
  - Revenue implications
  - Cost structure changes
  - Competitive position
  - Growth prospects
  - Risk factors

### 3. Trading Logic
The strategy generates signals based on:

```
IF sentiment_score > 0.7 AND confidence > 0.8:
    → BUY signal
ELIF sentiment_score < -0.7 AND confidence > 0.8:
    → SELL signal
ELSE:
    → HOLD (flat)
```

### 4. Signal Persistence
All signals are logged to:
- **Firestore Collection**: `tradingSignals`
- **PostgreSQL**: `strategy_logs` table
- **Dashboard Display**: Real-time signal monitoring

## Architecture

```
┌─────────────────┐
│  Alpaca News    │
│      API        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ News Fetcher    │
│ (news_fetcher)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Gemini 1.5     │
│    Flash        │
│ (llm_sentiment  │
│     _alpha)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Signal Writer   │
│ (Firestore)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Dashboard UI    │
│ (tradingSignals)│
└─────────────────┘
```

## Configuration

### Environment Variables

```bash
# Required
APCA_API_KEY_ID=<your-alpaca-key>
APCA_API_SECRET_KEY=<your-alpaca-secret>
APCA_API_BASE_URL=https://paper-api.alpaca.markets
FIREBASE_PROJECT_ID=<your-gcp-project>
DATABASE_URL=<postgresql-connection-string>

# Optional
STRATEGY_SYMBOLS=SPY,QQQ,IWM  # Default: SPY,IWM,QQQ
VERTEX_AI_MODEL_ID=gemini-1.5-flash  # Default: gemini-2.5-flash
VERTEX_AI_LOCATION=us-central1  # Default: us-central1
```

### Strategy Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sentiment_threshold` | 0.7 | Minimum absolute sentiment score for action |
| `confidence_threshold` | 0.8 | Minimum confidence level for action |
| `news_lookback_hours` | 24 | How many hours of news to analyze |
| `position_size` | 1 | Number of shares per trade |

## Usage

### Basic Execution (Dry Run)

```bash
python -m backend.strategy_engine.sentiment_strategy_driver
```

This will:
1. Fetch news from Alpaca
2. Analyze sentiment with Gemini
3. Generate signals
4. Log to Firestore and PostgreSQL
5. **NOT execute trades** (dry run)

### Execute Trades

```bash
python -m backend.strategy_engine.sentiment_strategy_driver --execute
```

### Custom Configuration

```bash
# Analyze specific symbols
python -m backend.strategy_engine.sentiment_strategy_driver --symbols AAPL,MSFT,GOOGL

# Adjust thresholds
python -m backend.strategy_engine.sentiment_strategy_driver \
  --sentiment-threshold 0.6 \
  --confidence-threshold 0.75

# Longer lookback period
python -m backend.strategy_engine.sentiment_strategy_driver \
  --news-lookback-hours 48
```

### Scheduled Execution

Add to cron for regular execution:

```bash
# Run every hour during market hours
0 9-16 * * 1-5 cd /workspace && python -m backend.strategy_engine.sentiment_strategy_driver --execute
```

Or use Cloud Scheduler:

```yaml
schedule: "0 9-16 * * 1-5"
timeZone: "America/New_York"
target:
  uri: https://your-cloud-run-url/run-sentiment-strategy
```

## Output Format

### Console Output

```
================================================================================
LLM Sentiment Strategy - 2024-12-30
Symbols: ['SPY', 'QQQ', 'IWM']
Execute trades: False
Sentiment threshold: 0.7
Confidence threshold: 0.8
News lookback: 24 hours
================================================================================

============================================================
Processing symbol: SPY
============================================================
Fetching news for SPY (last 24 hours)...
Found 15 news items, 12 after filtering
Analyzing sentiment with Gemini 1.5 Flash...

Sentiment Analysis Results:
  Action: BUY
  Sentiment Score: 0.85
  Confidence: 0.92
  Cash Flow Impact: Positive revenue impact from new product launch...
  
  AI Reasoning:
    The Federal Reserve's dovish stance combined with strong Q4 earnings 
    suggests improved cash flow generation in the near term. The S&P 500 
    index is likely to benefit from increased investor confidence...

Writing signal to Firestore tradingSignals collection...
Signal saved to Firestore: abc123def456

DRY RUN MODE - No trade executed
Would execute: BUY SPY
```

### Firestore Document (`tradingSignals` collection)

```json
{
  "strategy_id": "uuid-strategy-id",
  "strategy_name": "LLM Sentiment Alpha",
  "symbol": "SPY",
  "action": "BUY",
  "reason": "Strong positive sentiment (score: 0.85, confidence: 0.92)...",
  "sentiment_score": 0.85,
  "confidence": 0.92,
  "llm_reasoning": "The Federal Reserve's dovish stance...",
  "cash_flow_impact": "Positive revenue impact from new product launch...",
  "model_id": "gemini-1.5-flash",
  "signal_payload": {
    "news_count": 12,
    "sentiment_score": 0.85,
    "confidence": 0.92,
    "cash_flow_impact": "...",
    "llm_reasoning": "...",
    "target_symbols": ["SPY"],
    "analyzed_at": "2024-12-30T14:30:00Z",
    "model_id": "gemini-1.5-flash"
  },
  "did_trade": false,
  "timestamp": "2024-12-30T14:30:00Z",
  "created_at": "2024-12-30T14:30:00Z"
}
```

## Dashboard Integration

The strategy automatically writes signals to the `tradingSignals` Firestore collection, which can be queried and displayed in the React dashboard.

### Example Query (Frontend)

```typescript
import { collection, query, orderBy, limit, onSnapshot } from 'firebase/firestore';

// Subscribe to latest signals
const signalsRef = collection(db, 'tradingSignals');
const q = query(
  signalsRef,
  orderBy('timestamp', 'desc'),
  limit(10)
);

onSnapshot(q, (snapshot) => {
  const signals = snapshot.docs.map(doc => ({
    id: doc.id,
    ...doc.data()
  }));
  // Display in UI
});
```

### Example Display Component

```tsx
<Card>
  <CardHeader>
    <CardTitle>Latest AI Signals</CardTitle>
  </CardHeader>
  <CardContent>
    {signals.map(signal => (
      <div key={signal.id} className="mb-4">
        <div className="flex items-center justify-between">
          <span className="font-bold">{signal.symbol}</span>
          <Badge variant={signal.action === 'BUY' ? 'success' : 'destructive'}>
            {signal.action}
          </Badge>
        </div>
        <div className="text-sm text-muted-foreground">
          Sentiment: {signal.sentiment_score.toFixed(2)} | 
          Confidence: {(signal.confidence * 100).toFixed(0)}%
        </div>
        <div className="text-sm mt-2">
          {signal.llm_reasoning}
        </div>
      </div>
    ))}
  </CardContent>
</Card>
```

## Risk Management

The strategy implements several risk controls:

1. **Daily Trade Limits**: Maximum number of trades per day (configured via `strategy_limits` table)
2. **Notional Limits**: Maximum daily trading volume (configured via `strategy_limits` table)
3. **Confidence Threshold**: Only act on high-confidence signals (default: 0.8)
4. **Sentiment Threshold**: Only act on strong sentiment signals (default: 0.7)

## Monitoring & Debugging

### View Strategy Logs (PostgreSQL)

```sql
SELECT 
  created_at,
  symbol,
  decision,
  reason,
  signal_payload,
  did_trade
FROM strategy_logs
WHERE strategy_id = (SELECT id FROM strategy_definitions WHERE name = 'llm_sentiment_alpha')
ORDER BY created_at DESC
LIMIT 10;
```

### View Firestore Signals

```bash
# Using Firebase CLI
firebase firestore:get tradingSignals --limit 10 --order-by timestamp --order-direction desc

# Or check Firebase Console
# https://console.firebase.google.com/project/<your-project>/firestore/data/tradingSignals
```

### Check Vertex AI Usage

```bash
# View Gemini API usage in GCP Console
gcloud logging read "resource.type=aiplatform.googleapis.com" --limit 50
```

## Performance Optimization

### Caching News Fetches

To avoid redundant API calls, consider implementing a news cache:

```python
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=100)
def cached_fetch_news(symbol: str, cache_key: str):
    return fetch_news_by_symbol(symbol)

# Use cache_key based on hour to refresh hourly
cache_key = datetime.now().strftime("%Y%m%d%H")
news = cached_fetch_news("SPY", cache_key)
```

### Batch Processing

Process multiple symbols in parallel:

```python
import asyncio

async def process_all_symbols(symbols):
    tasks = [process_symbol(s) for s in symbols]
    await asyncio.gather(*tasks)
```

## Cost Considerations

### Alpaca News API
- **Free Tier**: Limited to basic news access
- **Paid Tier**: Unlimited news access with lower latency

### Vertex AI (Gemini)
- **Pricing**: ~$0.00025 per 1K characters (input) + ~$0.00075 per 1K characters (output)
- **Estimated Cost**: ~$0.01-0.05 per analysis (depending on news volume)
- **Daily Cost**: For 3 symbols analyzed hourly during market hours: ~$1-3/day

### Optimization Tips
1. Filter news for relevance before sending to Gemini
2. Batch multiple news items into single analysis request
3. Use shorter lookback periods during low-volatility periods
4. Implement smart caching to avoid redundant analyses

## Testing

### Unit Tests

```bash
pytest tests/test_llm_sentiment_alpha.py -v
```

### Integration Test

```bash
# Test with single symbol, dry run
python -m backend.strategy_engine.sentiment_strategy_driver \
  --symbols SPY \
  --news-lookback-hours 1
```

### Mock Gemini Responses

For testing without Vertex AI costs:

```python
from unittest.mock import Mock, patch

@patch('backend.strategy_engine.strategies.llm_sentiment_alpha.analyze_sentiment_with_gemini')
def test_strategy(mock_analyze):
    mock_analyze.return_value = SentimentAnalysis(
        sentiment_score=0.85,
        confidence=0.92,
        reasoning="Test reasoning",
        cash_flow_impact="Positive",
        action="BUY",
        target_symbols=["SPY"]
    )
    # Test logic...
```

## Troubleshooting

### Issue: No news fetched

**Cause**: Invalid Alpaca credentials or no news available

**Solution**:
```bash
# Verify credentials
echo $APCA_API_KEY_ID
echo $APCA_API_SECRET_KEY
echo $APCA_API_BASE_URL

# Test news API directly
python -c "from backend.strategy_engine.news_fetcher import fetch_news_by_symbol; print(fetch_news_by_symbol('SPY', 1))"
```

### Issue: Vertex AI initialization failed

**Cause**: Missing GCP credentials or wrong project

**Solution**:
```bash
# Set up Application Default Credentials
gcloud auth application-default login

# Verify project
echo $FIREBASE_PROJECT_ID

# Test Vertex AI
python -c "from backend.common.vertex_ai import init_vertex_ai_or_log; init_vertex_ai_or_log()"
```

### Issue: Firestore write failed

**Cause**: Missing Firebase permissions or wrong project

**Solution**:
```bash
# Verify Firebase project
firebase use

# Check Firestore permissions in Firebase Console
# Service account needs "Cloud Datastore User" role
```

## Future Enhancements

1. **Multi-Source News**: Integrate additional news sources (Twitter, Reddit, Bloomberg)
2. **Historical Backtesting**: Test strategy performance on historical data
3. **Dynamic Thresholds**: Adjust thresholds based on market volatility
4. **Risk-Adjusted Position Sizing**: Scale position size based on confidence and volatility
5. **Portfolio-Level Analysis**: Analyze news impact on entire portfolio
6. **Real-Time Streaming**: Process news in real-time via websocket streams
7. **Sentiment Trend Analysis**: Track sentiment changes over time
8. **Multi-Model Ensemble**: Combine multiple LLMs for consensus signals

## References

- [Alpaca News API Documentation](https://docs.alpaca.markets/docs/news-api)
- [Vertex AI Gemini Documentation](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini)
- [Firebase Firestore Documentation](https://firebase.google.com/docs/firestore)

## Support

For questions or issues:
1. Check logs in Cloud Run / Cloud Functions
2. Review Vertex AI quotas and limits
3. Verify all environment variables are set correctly
4. Check Firestore security rules
