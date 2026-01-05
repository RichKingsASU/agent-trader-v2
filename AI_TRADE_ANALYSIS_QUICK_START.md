# AI Trade Analysis - Quick Start Guide

## What Was Implemented

AI-powered post-game trade analysis using **Gemini 1.5 Flash** that automatically evaluates every closed shadow trade and provides actionable feedback.

### Features

✅ **Automatic Trigger**: Analyzes trades when status changes to `CLOSED`  
✅ **Gemini 1.5 Flash**: Uses Google's latest AI model for fast, accurate analysis  
✅ **Letter Grades**: A-F scoring based on trade discipline and execution  
✅ **Quant Tips**: Actionable feedback for improvement  
✅ **UI Integration**: Beautiful display in TradeHistoryTable component  
✅ **Context-Aware**: Evaluates trades against GEX regime and sentiment  

## Architecture

```
shadowTradeHistory/{tradeId} → status: CLOSED
        ↓
Cloud Function (analyze_closed_trade)
        ↓
Gemini 1.5 Flash API
        ↓
ai_analysis saved to Firestore
        ↓
UI displays grade + feedback
```

## Quick Start

### 1. Install Dependencies

```bash
cd functions
pip install -r requirements.txt
```

New dependency added:
- `google-cloud-aiplatform>=1.38.0`

### 2. Configure Vertex AI

Set environment variables for Cloud Functions:

```bash
# Option A: Using Firebase CLI
firebase functions:config:set \
  vertex.project_id="your-gcp-project-id" \
  vertex.location="us-central1"

# Option B: Using .env file (local testing)
export VERTEX_AI_PROJECT_ID="your-gcp-project-id"
export VERTEX_AI_LOCATION="us-central1"
export VERTEX_AI_MODEL_ID="gemini-1.5-flash"
```

### 3. Enable Vertex AI API

```bash
gcloud services enable aiplatform.googleapis.com
```

Or visit: https://console.cloud.google.com/apis/library/aiplatform.googleapis.com

### 4. Deploy Cloud Function

```bash
firebase deploy --only functions:analyze_closed_trade
```

Expected output:
```
✔ functions[analyze_closed_trade(us-central1)] Successful update operation.
Function URL: https://us-central1-your-project.cloudfunctions.net/analyze_closed_trade
```

### 5. Test the Feature

#### Option A: Using Test Script

```bash
python scripts/test_ai_trade_analysis.py
```

This will:
1. Create a test shadow trade
2. Close it automatically
3. Wait for AI analysis
4. Display the results

#### Option B: Manual Testing

1. Create a shadow trade (via API or UI):
```bash
POST /trades/execute
{
  "symbol": "SPY",
  "side": "BUY",
  "quantity": 10,
  "notional": 4500.00,
  // ... other fields
}
```

2. Close the trade:
```bash
POST /trades/close-shadow
{
  "shadow_id": "your-trade-id",
  "exit_reason": "Profit target hit"
}
```

3. Check Firestore (should see `ai_analysis` field within 5-10 seconds):
```json
{
  "ai_analysis": {
    "grade": "A",
    "feedback": "Excellent execution...",
    "analyzed_at": "2025-01-15T14:32:00Z",
    "model": "gemini-1.5-flash"
  }
}
```

### 6. View in UI

Open the TradeHistoryTable component and expand a closed trade:

```typescript
import { TradeHistoryTable } from "@/components/TradeHistoryTable";

<TradeHistoryTable trades={shadowTrades} />
```

The AI analysis appears at the top with:
- Color-coded grade badge (Green = A, Red = F)
- Actionable "Quant Tip" for improvement

## Files Changed/Created

### Backend (Cloud Functions)
- ✅ `functions/main.py` - Added trigger and analysis logic
  - `analyze_closed_trade()` - Firestore trigger function
  - `_analyze_trade_with_gemini()` - Gemini API integration
- ✅ `functions/requirements.txt` - Added `google-cloud-aiplatform>=1.38.0`

### Backend (FastAPI)
- ✅ `backend/strategy_service/routers/trades.py` - Added close endpoint
  - `POST /trades/close-shadow` - Close shadow trades

### Frontend
- ✅ `frontend/src/components/AIPostGame.tsx` - New component for AI display
- ✅ `frontend/src/components/TradeHistoryTable.tsx` - Integrated AIPostGame component

### Documentation
- ✅ `docs/AI_TRADE_ANALYSIS.md` - Comprehensive guide
- ✅ `AI_TRADE_ANALYSIS_QUICK_START.md` - This file
- ✅ `scripts/test_ai_trade_analysis.py` - Test script

## Example Output

### Grade A Trade
```
🤖 AI POST-GAME ANALYSIS
============================================================

📊 GRADE: A

💡 QUANT TIP:
   Excellent execution. You correctly identified positive GEX 
   regime and bought the dip with discipline. Entry timing at 
   VWAP support was textbook. Consider scaling position size 
   on high-conviction setups like this one.

🕒 Analyzed: 2025-01-15T14:32:00Z
🤖 Model: gemini-1.5-flash
============================================================
```

### Grade D Trade
```
🤖 AI POST-GAME ANALYSIS
============================================================

📊 GRADE: D

💡 QUANT TIP:
   Poor execution. Negative GEX regime (-$800M) creates 
   volatility amplification. In this environment, breakouts 
   often fail as dealers amplify reversals. Next time, verify 
   GEX regime before chasing momentum.

🕒 Analyzed: 2025-01-15T11:46:00Z
🤖 Model: gemini-1.5-flash
============================================================
```

## Troubleshooting

### Issue: "Vertex AI not configured"

**Solution:**
```bash
# Check environment variables
firebase functions:config:get

# Set if missing
firebase functions:config:set vertex.project_id="YOUR_PROJECT_ID"
firebase deploy --only functions
```

### Issue: AI analysis not appearing

**Check:**
1. Is trade status = `CLOSED`? (Only closed trades analyzed)
2. Cloud Function deployed? `firebase deploy --only functions:analyze_closed_trade`
3. Vertex AI API enabled? Check GCP Console
4. Check logs: `firebase functions:log --only analyze_closed_trade`

### Issue: "Permission denied" errors

**Solution:**
```bash
# Grant Vertex AI permissions to Cloud Functions service account
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

## Cost Estimate

**Gemini 1.5 Flash is extremely cheap:**
- ~$0.000024 per trade analysis
- 10,000 trades/month = $0.24/month
- Essentially free for most use cases

## Next Steps

1. **Deploy to Production**
   ```bash
   firebase deploy --only functions:analyze_closed_trade
   ```

2. **Test with Real Trades**
   - Execute a few shadow trades
   - Close them manually
   - Verify AI analysis appears

3. **Monitor Performance**
   ```bash
   firebase functions:log --only analyze_closed_trade
   ```

4. **Customize Prompts** (optional)
   - Edit `_analyze_trade_with_gemini()` in `functions/main.py`
   - Adjust grading criteria for your strategy

## Support

- 📖 **Full Documentation**: See `docs/AI_TRADE_ANALYSIS.md`
- 🧪 **Test Script**: Run `python scripts/test_ai_trade_analysis.py`
- 📊 **UI Preview**: Mock data with AI analysis in TradeHistoryTable
- 🔍 **Logs**: `firebase functions:log --only analyze_closed_trade`

## Demo

Mock trades with AI analysis are already visible in the UI:
- Trade #1 (SPY +0.38%): Grade A - "Excellent execution"
- Trade #3 (TSLA -0.54%): Grade D - "Poor execution, negative GEX"

Just expand any closed trade in the TradeHistoryTable to see the AI analysis!

---

**Ready to use!** 🚀

The feature is fully implemented and ready for testing. Just deploy the Cloud Function and start closing trades.
