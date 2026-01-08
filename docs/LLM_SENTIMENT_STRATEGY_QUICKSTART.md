# LLM Sentiment Strategy - Quick Start Guide

## What is this?

The **LLM Sentiment Alpha** strategy uses Gemini 1.5 Flash AI to analyze news headlines and generate trading signals based on deep reasoning about future cash flows and business fundamentals - not just simple positive/negative scoring.

## How it works

```
Alpaca News → Gemini Analysis → Trading Signal → Firestore Dashboard
```

1. **Fetches** latest news from Alpaca News API
2. **Analyzes** with Gemini 1.5 Flash (reasoning-driven, not just sentiment scoring)
3. **Generates** BUY/SELL/HOLD signals based on thresholds
4. **Logs** to Firestore `tradingSignals` collection for dashboard display

## Quick Start (5 minutes)

### Step 1: Set Environment Variables

```bash
# Required
export APCA_API_KEY_ID="your-alpaca-key"
export APCA_API_SECRET_KEY="your-alpaca-secret"
export APCA_API_BASE_URL="https://paper-api.alpaca.markets"
export FIREBASE_PROJECT_ID="your-gcp-project"
export DATABASE_URL="postgresql://..."

# Optional
export STRATEGY_SYMBOLS="SPY,QQQ,IWM"
export VERTEX_AI_MODEL_ID="gemini-1.5-flash"
```

### Step 2: Install Dependencies

```bash
cd /workspace
pip install -r backend/requirements.txt
```

### Step 3: Run (Dry Run)

```bash
python -m backend.strategy_engine.sentiment_strategy_driver
```

Expected output:
```
================================================================================
LLM Sentiment Strategy - 2024-12-30
Symbols: ['SPY', 'QQQ', 'IWM']
Execute trades: False
================================================================================

Processing symbol: SPY
Fetching news for SPY (last 24 hours)...
Found 15 news items, 12 after filtering
Analyzing sentiment with Gemini 1.5 Flash...

Sentiment Analysis Results:
  Action: BUY
  Sentiment Score: 0.85
  Confidence: 0.92
  Cash Flow Impact: Positive revenue growth expected...
  
Writing signal to Firestore tradingSignals collection...
Signal saved to Firestore: abc123def456

DRY RUN MODE - No trade executed
```

### Step 4: View Results

**Option A: Check Firestore Console**
1. Open Firebase Console: https://console.firebase.google.com
2. Navigate to Firestore Database
3. View `tradingSignals` collection

**Option B: Query from Terminal**

```bash
firebase firestore:get tradingSignals --limit 5
```

**Option C: View in Dashboard**

The signals will automatically appear in your React dashboard if you have the AISignalWidget component installed.

## Strategy Parameters

### Thresholds (Default Values)

- **Sentiment Threshold**: 0.7 (scale: -1.0 to 1.0)
  - BUY when sentiment > 0.7
  - SELL when sentiment < -0.7
  
- **Confidence Threshold**: 0.8 (scale: 0.0 to 1.0)
  - Only act when AI is >80% confident

### Customize Thresholds

```bash
# More aggressive (lower thresholds)
python -m backend.strategy_engine.sentiment_strategy_driver \
  --sentiment-threshold 0.5 \
  --confidence-threshold 0.7

# More conservative (higher thresholds)
python -m backend.strategy_engine.sentiment_strategy_driver \
  --sentiment-threshold 0.8 \
  --confidence-threshold 0.9
```

## Execute Real Trades

⚠️ **Warning**: This will execute paper trades in your Alpaca account

```bash
python -m backend.strategy_engine.sentiment_strategy_driver --execute
```

## Common Use Cases

### 1. Monitor Specific Stocks

```bash
python -m backend.strategy_engine.sentiment_strategy_driver --symbols AAPL,MSFT,NVDA
```

### 2. Analyze Recent News Only

```bash
python -m backend.strategy_engine.sentiment_strategy_driver --news-lookback-hours 6
```

### 3. Scheduled Execution (Hourly during market hours)

Add to crontab:

```bash
0 9-16 * * 1-5 cd /workspace && python -m backend.strategy_engine.sentiment_strategy_driver --execute
```

### 4. Custom Pipeline

```python
from backend.strategy_engine.news_fetcher import fetch_news_by_symbol
from backend.strategy_engine.strategies.llm_sentiment_alpha import make_decision

# Fetch news
news = fetch_news_by_symbol("AAPL", lookback_hours=12)

# Analyze
decision = make_decision(news, "AAPL", sentiment_threshold=0.6, confidence_threshold=0.75)

# Access results
print(f"Action: {decision['action']}")
print(f"Sentiment: {decision['signal_payload']['sentiment_score']}")
print(f"Reasoning: {decision['signal_payload']['llm_reasoning']}")
```

## What the AI Analyzes

Unlike simple sentiment scoring, Gemini analyzes:

1. **Cash Flow Impact**
   - How will this news affect future cash generation?
   - Revenue implications (demand, pricing, market share)
   - Cost structure changes
   - Capital requirements

2. **Business Fundamentals**
   - Competitive position
   - Growth prospects
   - Risk factors
   - Management quality

3. **Time Horizon**
   - Immediate impact (0-3 months)
   - Near-term (3-12 months)
   - Long-term (12+ months)

## Example AI Analysis

**Input News:**
> "Apple announces new AI-powered iPhone with 20% higher price point, pre-orders exceed expectations by 300%"

**AI Analysis:**
```json
{
  "sentiment_score": 0.85,
  "confidence": 0.92,
  "reasoning": "Strong positive signal for Apple's cash flows. The premium pricing 
                combined with exceptional demand indicates pricing power and margin 
                expansion. 300% above expectations suggests robust demand elasticity 
                at higher price points, which should drive both revenue growth and 
                improved operating margins in Q1-Q2. This represents a fundamental 
                shift in the iPhone business model toward premium positioning.",
  "cash_flow_impact": "Positive revenue growth (+15-20% YoY expected) with margin 
                       expansion (+2-3 points) leading to 20-25% free cash flow 
                       increase in coming quarters.",
  "action": "BUY"
}
```

## Output Data Structure

### Firestore Document (`tradingSignals` collection)

```json
{
  "strategy_id": "uuid",
  "strategy_name": "LLM Sentiment Alpha",
  "symbol": "AAPL",
  "action": "BUY",
  "sentiment_score": 0.85,
  "confidence": 0.92,
  "llm_reasoning": "Strong positive signal for Apple's cash flows...",
  "cash_flow_impact": "Positive revenue growth...",
  "model_id": "gemini-1.5-flash",
  "did_trade": false,
  "timestamp": "2024-12-30T14:30:00Z"
}
```

## Troubleshooting

### Issue: "No news found"

**Solution**: Check if symbol has recent news
```bash
# Test news API
python -c "from backend.strategy_engine.news_fetcher import fetch_news_by_symbol; print(len(fetch_news_by_symbol('SPY', 24)))"
```

### Issue: "Vertex AI initialization failed"

**Solution**: Set up GCP credentials
```bash
gcloud auth application-default login
export FIREBASE_PROJECT_ID="your-project"
```

### Issue: "Firestore write failed"

**Solution**: Check Firebase permissions
```bash
firebase use  # Verify correct project
# Ensure service account has "Cloud Datastore User" role
```

## Cost Estimate

For 3 symbols analyzed hourly during market hours (7 hours × 5 days = 35 runs/week):

- **Alpaca News API**: Free (basic tier) or $9/month (unlimited)
- **Vertex AI (Gemini)**: ~$0.02 per analysis = **~$0.70/week** or **~$3/month**
- **Firestore**: Free tier sufficient for signal storage

**Total**: < $5/month for automated AI-driven news analysis

## Next Steps

1. **Review signals** in Firestore console
2. **Integrate with dashboard** using AISignalWidget component
3. **Set up scheduled execution** via cron or Cloud Scheduler
4. **Monitor performance** and adjust thresholds
5. **Enable trade execution** when ready (--execute flag)

## Full Documentation

See [README_SENTIMENT.md](../backend/strategy_engine/strategies/README_SENTIMENT.md) for complete documentation including:
- Architecture details
- Risk management
- Performance optimization
- Monitoring & debugging
- Cost considerations

## Support

Questions? Check the troubleshooting section in the full README or review:
- Console logs for error details
- Firestore console for signal history
- Vertex AI logs in GCP Console
