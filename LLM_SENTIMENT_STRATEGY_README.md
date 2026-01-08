# LLM Sentiment Strategy - Complete Implementation

> **Status**: ✅ **PRODUCTION READY**

## Quick Links

- 📚 [Quick Start Guide](docs/LLM_SENTIMENT_STRATEGY_QUICKSTART.md)
- 📖 [Full Documentation](backend/strategy_engine/strategies/README_SENTIMENT.md)
- 📊 [Implementation Summary](docs/LLM_SENTIMENT_IMPLEMENTATION_SUMMARY.md)

## What Is This?

An **LLM-Enhanced Sentiment Strategy** that uses **Gemini 1.5 Flash** to analyze news headlines and generate trading signals based on deep reasoning about **future cash flows** and **business fundamentals** - not just simple sentiment scoring.

## Key Innovation

Traditional sentiment analysis: _"This headline is positive/negative"_

**This strategy**: _"How will this news impact future cash generation? What are the revenue implications? How does it affect competitive positioning?"_

## Architecture

```
Alpaca News API → Gemini 1.5 Flash → Trading Signal → Firestore Dashboard
```

1. **Fetches** latest news from Alpaca
2. **Analyzes** with Gemini (reasoning-driven)
3. **Generates** BUY/SELL/HOLD signals
4. **Logs** to `tradingSignals` Firestore collection

## Quick Start (3 Steps)

### 1. Set Environment Variables

```bash
export APCA_API_KEY_ID="your-alpaca-key"
export APCA_API_SECRET_KEY="your-alpaca-secret"
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
export FIREBASE_PROJECT_ID="your-gcp-project"
export DATABASE_URL="postgresql://..."
```

### 2. Run (Dry Run)

```bash
python3 -m backend.strategy_engine.sentiment_strategy_driver
```

### 3. View Results

Check Firestore Console → `tradingSignals` collection

Or use the convenience script:

```bash
./scripts/run_sentiment_strategy.sh
```

## Strategy Logic

```
IF sentiment_score > 0.7 AND confidence > 0.8:
    → BUY signal
ELIF sentiment_score < -0.7 AND confidence > 0.8:
    → SELL signal
ELSE:
    → HOLD
```

Thresholds are configurable via command-line arguments.

## Output Example

```
Sentiment Analysis Results:
  Action: BUY
  Sentiment Score: 0.85
  Confidence: 0.92
  Cash Flow Impact: Fed rate cuts will boost valuations...
  
  AI Reasoning:
    The Federal Reserve's dovish pivot combined with strong 
    Q4 earnings suggests favorable conditions. Key drivers:
    1) Lower interest rates reduce discount rates
    2) Strong consumer spending supports revenue growth
    3) Corporate margins remain resilient

Signal saved to Firestore: abc123xyz789
```

## What Gets Logged to Firestore

Every signal includes:
- **Action**: BUY/SELL/HOLD
- **Sentiment Score**: -1.0 to 1.0
- **Confidence**: 0.0 to 1.0
- **LLM Reasoning**: Full AI analysis
- **Cash Flow Impact**: Business fundamentals assessment
- **Model ID**: gemini-1.5-flash
- **Timestamp**: When analysis was performed

Perfect for dashboard display and historical analysis.

## Files Created

```
backend/strategy_engine/
├── strategies/
│   ├── llm_sentiment_alpha.py      # Core sentiment engine
│   └── README_SENTIMENT.md         # Full docs
├── news_fetcher.py                 # Alpaca News API
├── signal_writer.py                # Firestore writer
├── sentiment_strategy_driver.py    # Main orchestration
└── test_sentiment_strategy.py      # Test suite

docs/
├── LLM_SENTIMENT_STRATEGY_QUICKSTART.md
└── LLM_SENTIMENT_IMPLEMENTATION_SUMMARY.md

scripts/
└── run_sentiment_strategy.sh       # Convenience runner
```

## Usage Examples

### Basic
```bash
# Dry run (no trades)
python3 -m backend.strategy_engine.sentiment_strategy_driver

# Execute trades
python3 -m backend.strategy_engine.sentiment_strategy_driver --execute
```

### Advanced
```bash
# Specific symbols
python3 -m backend.strategy_engine.sentiment_strategy_driver \
  --symbols AAPL,MSFT,NVDA

# Adjust thresholds (more aggressive)
python3 -m backend.strategy_engine.sentiment_strategy_driver \
  --sentiment-threshold 0.5 \
  --confidence-threshold 0.7

# Longer lookback period
python3 -m backend.strategy_engine.sentiment_strategy_driver \
  --news-lookback-hours 48
```

### Scheduled Execution

**Cron** (hourly during market hours):
```bash
0 9-16 * * 1-5 cd /workspace && ./scripts/run_sentiment_strategy.sh --execute
```

**Cloud Scheduler**:
```yaml
schedule: "0 9-16 * * 1-5"
timeZone: "America/New_York"
target:
  uri: https://your-cloud-run-url/run-sentiment-strategy
```

## Cost Estimate

| Service | Cost |
|---------|------|
| Alpaca News API | Free (basic) |
| Vertex AI (Gemini) | ~$0.02 per analysis |
| Firestore | Free tier |

**Daily cost** (3 symbols, 7 hourly runs): ~$0.42
**Monthly**: ~$10

Very affordable for institutional-grade AI analysis!

## Testing

### Quick Validation
```bash
python3 -c "from backend.strategy_engine.strategies import llm_sentiment_alpha; print('✅ OK')"
```

### Full Test Suite
```bash
python3 -m backend.strategy_engine.test_sentiment_strategy
```

Expected: All tests pass ✅

## Dashboard Integration

Signals are automatically written to Firestore and ready for display:

```tsx
// React component example
import { collection, query, orderBy } from 'firebase/firestore';

const signalsRef = collection(db, 'tradingSignals');
const q = query(signalsRef, orderBy('timestamp', 'desc'));

// Subscribe and display
useFirestoreQuery(q, (signals) => {
  // Render signal cards with sentiment, confidence, reasoning
});
```

## Monitoring

### Firestore Console
https://console.firebase.google.com → Firestore → `tradingSignals`

### PostgreSQL Logs
```sql
SELECT * FROM strategy_logs 
WHERE strategy_id = (
  SELECT id FROM strategy_definitions 
  WHERE name = 'llm_sentiment_alpha'
)
ORDER BY created_at DESC;
```

### Vertex AI Usage
```bash
gcloud logging read "resource.type=aiplatform.googleapis.com" --limit 50
```

## Production Deployment

### Option 1: Cloud Run (Recommended)
```bash
gcloud run deploy sentiment-strategy \
  --source . \
  --region us-central1 \
  --set-env-vars FIREBASE_PROJECT_ID=$PROJECT_ID
```

### Option 2: Kubernetes CronJob
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: sentiment-strategy
spec:
  schedule: "0 9-16 * * 1-5"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: strategy
            image: gcr.io/$PROJECT_ID/sentiment-strategy
            command: ["python3", "-m", "backend.strategy_engine.sentiment_strategy_driver", "--execute"]
```

### Option 3: Local Cron
```bash
crontab -e
# Add:
0 9-16 * * 1-5 cd /workspace && ./scripts/run_sentiment_strategy.sh --execute
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| No news found | Verify Alpaca credentials, check symbol has recent news |
| Vertex AI error | Run `gcloud auth application-default login` |
| Firestore write failed | Check Firebase project ID and permissions |
| Import errors | Run `pip3 install -r backend/requirements.txt` |

## Next Steps

1. ✅ **Review Quick Start** - Get familiar with basic usage
2. ✅ **Run Test Suite** - Validate your environment
3. ✅ **Try Dry Run** - Test with real news data
4. ✅ **Deploy to Production** - Schedule automated runs
5. ✅ **Integrate Dashboard** - Display signals in UI
6. ✅ **Monitor Performance** - Track signal quality

## AI Analysis Example

**Input**: "Apple announces 20% higher iPhone pricing, pre-orders exceed expectations by 300%"

**AI Output**:
```json
{
  "sentiment_score": 0.85,
  "confidence": 0.92,
  "action": "BUY",
  "reasoning": "Strong positive signal. Premium pricing + exceptional 
                demand indicates pricing power and margin expansion. 
                300% above expectations suggests robust demand elasticity 
                at higher prices. Expect 15-20% YoY revenue growth with 
                2-3 point margin expansion, leading to 20-25% FCF increase.",
  "cash_flow_impact": "Positive revenue growth with margin expansion"
}
```

This is the kind of **deep, actionable analysis** you get with every signal.

## Key Features

- ✅ **Reasoning-Driven**: Not just sentiment, but business impact analysis
- ✅ **Cash Flow Focus**: Analyzes revenue, costs, and capital requirements
- ✅ **High Confidence**: Only acts on strong signals (0.7+ sentiment, 0.8+ confidence)
- ✅ **Risk Managed**: Daily trade limits and notional caps
- ✅ **Dashboard Ready**: Signals logged to Firestore with full context
- ✅ **Cost Effective**: ~$10/month for unlimited AI-driven analysis
- ✅ **Production Ready**: Complete with tests, docs, and deployment scripts

## Documentation

- **Quick Start**: [docs/LLM_SENTIMENT_STRATEGY_QUICKSTART.md](docs/LLM_SENTIMENT_STRATEGY_QUICKSTART.md)
- **Full Docs**: [backend/strategy_engine/strategies/README_SENTIMENT.md](backend/strategy_engine/strategies/README_SENTIMENT.md)
- **Implementation**: [docs/LLM_SENTIMENT_IMPLEMENTATION_SUMMARY.md](docs/LLM_SENTIMENT_IMPLEMENTATION_SUMMARY.md)

## Support

Questions? Check the docs or review:
1. Console logs for error details
2. Firestore console for signal history
3. Test suite output for validation

## Summary

🎯 **Strategy**: LLM-Enhanced Sentiment Analysis
🤖 **Model**: Gemini 1.5 Flash
📊 **Data Source**: Alpaca News API
💾 **Storage**: Firestore (`tradingSignals`)
✅ **Status**: Production Ready

**Built for**: Automated, AI-driven news sentiment trading with deep reasoning and cash flow analysis.

---

Ready to deploy! 🚀
