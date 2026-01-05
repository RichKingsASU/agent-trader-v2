# AI-Powered Trade Analysis (Post-Game Review)

## Overview

This feature provides **AI-powered post-game analysis** for every closed shadow trade using **Gemini 1.5 Flash**. When a trader closes a position, the system automatically evaluates trade quality, discipline, and execution against market conditions (GEX regime, sentiment) and provides actionable feedback.

## Architecture

### Cloud Function Trigger
```
users/{uid}/shadowTradeHistory/{tradeId} → CLOSED status
    ↓
Cloud Function: analyze_closed_trade()
    ↓
Gemini 1.5 Flash Analysis
    ↓
Store ai_analysis back in Firestore
```

### Components

1. **Backend Trigger** (`functions/main.py`)
   - Firestore trigger: `@firestore_fn.on_document_written(document="shadowTradeHistory/{tradeId}")`
   - Fires when a trade document is updated to `status: "CLOSED"`
   - Extracts trade context (entry/exit, P&L, GEX, sentiment)
   - Calls Gemini 1.5 Flash for analysis

2. **AI Analysis Engine** (`_analyze_trade_with_gemini()`)
   - Uses Gemini 1.5 Flash (`gemini-1.5-flash`)
   - Evaluates trade discipline and execution quality
   - Generates:
     - **Grade**: A-F letter grade
     - **Quant Tip**: Single actionable insight (max 100 words)

3. **UI Component** (`AIPostGame.tsx`)
   - Displays AI analysis on trade history cards
   - Color-coded grade badges (Green = A, Red = F)
   - Shows actionable "Quant Tip" for improvement

4. **Close Trade Endpoint** (`/trades/close-shadow`)
   - POST endpoint to close shadow trades
   - Records exit_price using current market data
   - Calculates final P&L
   - Triggers AI analysis via Firestore trigger

## Data Flow

### 1. Open Trade
```typescript
POST /trades/execute
{
  "symbol": "SPY",
  "side": "BUY",
  "quantity": 10,
  // ... other fields
}
```

**Firestore Document Created:**
```json
{
  "shadow_id": "abc123",
  "uid": "user123",
  "symbol": "SPY",
  "entry_price": "450.50",
  "status": "OPEN",
  "metadata": {
    "net_gex": "1500000000",
    "volatility_bias": "Bullish",
    "sentiment": "Positive"
  },
  "reasoning": "Positive GEX regime, buying dip"
}
```

### 2. Close Trade
```typescript
POST /trades/close-shadow
{
  "shadow_id": "abc123",
  "exit_reason": "Profit target hit"
}
```

**Firestore Document Updated (triggers AI analysis):**
```json
{
  "shadow_id": "abc123",
  "status": "CLOSED",  // ← Triggers Cloud Function
  "exit_price": "452.00",
  "final_pnl": "15.00",
  "final_pnl_percent": "0.33",
  "exit_reason": "Profit target hit"
}
```

### 3. AI Analysis (Automatic)
Cloud Function `analyze_closed_trade()` fires and updates:

```json
{
  "ai_analysis": {
    "grade": "A",
    "feedback": "Excellent execution. You correctly identified positive GEX regime and bought the dip. Consider tightening stops in volatile markets to protect profits.",
    "analyzed_at": "2025-01-15T14:32:00Z",
    "model": "gemini-1.5-flash"
  }
}
```

### 4. UI Display
The `TradeHistoryTable` component automatically shows the AI analysis when expanding a closed trade.

## Gemini Analysis Prompt

The AI uses the following evaluation criteria:

```
You are a Senior Quant analyzing a 0DTE Gamma Scalp trade.

Trade Details:
- Symbol: {symbol}
- Side: {side}
- Entry Price: ${entry_price}
- Exit Price: ${exit_price}
- P&L: ${pnl} ({pnl_percent}%)

Market Context at Entry:
- GEX (Gamma Exposure): {gex} ({regime})
- Sentiment: {sentiment}
- Strategy Reasoning: {reasoning}

Evaluate this trade:
1. Was this a disciplined trade given the GEX regime and sentiment?
2. Did the trader follow gamma scalping principles?
3. Was the P&L reasonable for the market conditions?

Provide:
- Grade: A-F
- One "Quant Tip": Actionable insight for next time (max 100 words)
```

## Grading Criteria

| Grade | Description |
|-------|-------------|
| **A** | Excellent execution, perfect market timing, disciplined risk management |
| **B** | Good execution, minor improvements possible |
| **C** | Average execution, several areas for improvement |
| **D** | Poor execution, violated multiple principles |
| **F** | Failed trade, lack of discipline or market awareness |

## Usage

### For Traders (Frontend)

1. **View Trade History**
   ```typescript
   import { TradeHistoryTable } from "@/components/TradeHistoryTable";
   
   <TradeHistoryTable trades={shadowTrades} />
   ```

2. **Expand Closed Trade**
   - Click the chevron icon to expand trade details
   - If trade is CLOSED and analyzed, AI analysis appears at the top
   - Shows grade badge and actionable feedback

3. **Close Open Trade (Manually)**
   ```typescript
   const closeTrade = async (shadowId: string) => {
     const response = await fetch('/trades/close-shadow', {
       method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({
         shadow_id: shadowId,
         exit_reason: 'Manual close'
       })
     });
     
     // AI analysis will be generated within ~5 seconds
   };
   ```

### For Backend Developers

1. **Testing AI Analysis**
   ```python
   from functions.main import _analyze_trade_with_gemini
   
   trade_data = {
       "symbol": "SPY",
       "entry_price": "450.50",
       "exit_price": "452.00",
       "current_pnl": "15.00",
       "pnl_percent": "0.33",
       "side": "BUY",
       "metadata": {
           "net_gex": "1500000000",
           "volatility_bias": "Bullish",
           "sentiment": "Positive"
       },
       "reasoning": "Positive GEX, bought the dip"
   }
   
   analysis = _analyze_trade_with_gemini(trade_data)
   print(f"Grade: {analysis['grade']}")
   print(f"Tip: {analysis['feedback']}")
   ```

2. **Manual Trigger (for debugging)**
   ```python
   # Manually trigger analysis for a specific trade
   from google.cloud import firestore
   
   db = firestore.Client()
   trade_ref = db.collection("shadowTradeHistory").document("trade_id_here")
   trade_ref.update({"status": "CLOSED"})  # Triggers Cloud Function
   ```

## Configuration

### Environment Variables

Set these in your Cloud Functions environment:

```bash
# Vertex AI Configuration
VERTEX_AI_PROJECT_ID=your-gcp-project-id
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_MODEL_ID=gemini-1.5-flash

# Firebase Functions will auto-configure these
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GCP_PROJECT=your-gcp-project-id
```

### Deploy Cloud Functions

```bash
cd functions
firebase deploy --only functions:analyze_closed_trade
```

### Update Dependencies

```bash
pip install -r functions/requirements.txt
```

Required packages:
- `google-cloud-aiplatform>=1.38.0`
- `firebase-functions`
- `firebase-admin`

## Example Scenarios

### Scenario 1: Perfect Gamma Scalp (Grade A)
```
Entry: $450.50 (BUY)
Exit: $452.00
GEX: +$1.5B (Bullish)
Sentiment: Positive
P&L: +0.33%

AI Grade: A
Tip: "Excellent execution. You correctly identified the positive GEX regime 
and bought the dip with discipline. Your entry timing was perfect at VWAP 
support. Consider scaling position size on high-conviction setups like this."
```

### Scenario 2: Broke Discipline (Grade D)
```
Entry: $450.50 (BUY)
Exit: $448.00
GEX: -$800M (Bearish)
Sentiment: Negative
P&L: -0.44%

AI Grade: D
Tip: "Poor execution. Negative GEX creates volatility amplification - you 
should fade rallies, not buy dips. This violated core gamma scalping principles. 
Next time, check GEX regime BEFORE entering and align with dealer flow."
```

### Scenario 3: Lucky Winner (Grade C)
```
Entry: $450.50 (SELL)
Exit: $449.00
GEX: +$1.2B (Bullish)
Sentiment: Positive
P&L: +0.33%

AI Grade: C
Tip: "This trade was profitable but contradicted the positive GEX regime. 
In bullish gamma, dips get bought - you got lucky with timing. Align your 
directional bias with GEX for more consistent results."
```

## Monitoring & Debugging

### Check Analysis Status

```typescript
// Query trades with AI analysis
const analyzedTrades = await db
  .collection("shadowTradeHistory")
  .where("status", "==", "CLOSED")
  .where("ai_analysis", "!=", null)
  .get();

console.log(`${analyzedTrades.size} trades analyzed`);
```

### Cloud Function Logs

```bash
# View Cloud Function logs
firebase functions:log --only analyze_closed_trade

# Filter for errors
firebase functions:log --only analyze_closed_trade | grep ERROR
```

### Re-analyze Failed Trades

If AI analysis fails, you can manually re-trigger:

```python
from google.cloud import firestore

db = firestore.Client()

# Find trades that failed analysis
failed_trades = db.collection("shadowTradeHistory") \
    .where("status", "==", "CLOSED") \
    .where("ai_analysis", "==", None) \
    .stream()

for trade in failed_trades:
    print(f"Re-triggering analysis for {trade.id}")
    # Remove ai_analysis field to allow re-analysis
    trade.reference.update({"ai_analysis": firestore.DELETE_FIELD})
    # Update timestamp to trigger function
    trade.reference.update({"last_updated": firestore.SERVER_TIMESTAMP})
```

## Security

- **Authentication**: Cloud Function trigger is internal, no external access
- **Authorization**: Only trade owner (uid) can close their own trades
- **Rate Limiting**: Vertex AI has built-in rate limits (60 requests/minute for Gemini 1.5 Flash)
- **Cost Control**: Analysis only runs once per trade (checked via `ai_analysis` field)

## Cost Estimate

**Gemini 1.5 Flash Pricing** (as of 2025):
- Input: $0.00001875 per 1K characters
- Output: $0.000075 per 1K characters

**Average Cost per Trade:**
- Input prompt: ~500 characters = $0.000009
- Output response: ~200 characters = $0.000015
- **Total per trade: ~$0.000024 (essentially free)**

**Monthly Cost for 10,000 trades:**
- $0.24/month

## Troubleshooting

### Issue: AI analysis not appearing

**Check:**
1. Is trade status = "CLOSED"? (Only closed trades are analyzed)
2. Check Cloud Function logs: `firebase functions:log`
3. Verify Vertex AI credentials are configured
4. Check `ai_analysis` field in Firestore document

### Issue: "Vertex AI not configured" error

**Fix:**
```bash
# Set environment variables
firebase functions:config:set \
  vertex.project_id="your-gcp-project-id" \
  vertex.location="us-central1"

# Redeploy functions
firebase deploy --only functions
```

### Issue: Analysis takes too long

**Typical timing:**
- Trade close → Firestore trigger: <1 second
- Gemini API call: 2-5 seconds
- Firestore update: <1 second
- **Total: 3-7 seconds**

If slower, check Vertex AI quotas and network latency.

## Future Enhancements

1. **Multi-Trade Analysis**: Analyze patterns across multiple trades
2. **Performance Tracking**: Track grade improvement over time
3. **Custom Prompts**: Allow users to customize analysis criteria
4. **Voice Feedback**: Convert Quant Tips to audio for mobile
5. **Backtesting Integration**: Compare AI grades with actual market outcomes

## Related Documentation

- [Shadow Mode Implementation](../SHADOW_PNL_IMPLEMENTATION_SUMMARY.md)
- [GEX Engine](../PHASE4_2_GEX_ENGINE_IMPLEMENTATION.md)
- [Vertex AI Documentation](https://cloud.google.com/vertex-ai/docs)

## Support

For issues or questions:
- Check Cloud Function logs: `firebase functions:log`
- Review Firestore documents in `shadowTradeHistory` collection
- Verify Vertex AI API is enabled in GCP Console
