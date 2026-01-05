# Automated Trading Journal - Quick Start Guide

## Overview

The **Automated Trading Journal** provides AI-powered trade analysis using Gemini 2.5 Flash. Every time a shadow trade closes, the system automatically:

1. ✅ Captures trade details (Entry, Exit, P&L)
2. 🧠 Analyzes with Gemini AI (Senior Quant perspective)
3. 📊 Assigns a Quant Grade (A-F)
4. 💾 Stores insights in Firestore
5. 📱 Displays in beautiful UI

## Architecture

```
shadowTradeHistory/{tradeId}
    │ (status: "OPEN" → "CLOSED")
    ↓
[Firestore Trigger]
    ↓
functions/journaling.py::analyze_closed_trade()
    ↓
├─ Fetch GEX regime data
├─ Build analysis prompt
└─ Call Gemini 2.5 Flash
    ↓
users/{uid}/tradeJournal/{tradeId}
    ↓
[Real-time UI Update]
    ↓
JournalEntry.tsx Component
```

## Components

### Backend: `functions/journaling.py`

**Firestore Trigger Function:**
- **Trigger:** `shadowTradeHistory/{tradeId}` on document update
- **Condition:** Status changes from any state to "CLOSED"
- **Action:** Analyzes trade with Gemini and stores insights

**Key Features:**
- ✅ Firestore trigger (automatic, no manual calls)
- ✅ GEX regime integration
- ✅ Gemini 2.5 Flash AI analysis
- ✅ Structured prompt engineering
- ✅ Grade extraction (A-F)
- ✅ Error handling with fallback

### Frontend: `frontend/src/components/JournalEntry.tsx`

**Two Components:**

1. **`TradeJournal`** - Full-page journal view
   - Real-time Firestore listener
   - Displays all journal entries
   - Grade distribution summary
   - Detailed AI analysis
   - Actionable improvements

2. **`TradeJournalWidget`** - Compact widget
   - Shows 3 most recent entries
   - Smaller format for dashboards
   - Quick grade overview

## Data Model

### Collection: `users/{uid}/tradeJournal/{tradeId}`

```typescript
{
  trade_id: string;              // Shadow trade ID
  uid: string;                   // User ID
  symbol: string;                // Ticker (e.g., "SPY")
  side: "BUY" | "SELL";         // Trade direction
  quantity: number;              // Number of shares
  entry_price: string;           // Entry price (precision)
  exit_price: string;            // Exit price (precision)
  realized_pnl: string;          // P&L in dollars
  pnl_percent: string;           // P&L percentage
  original_reasoning: string;    // Original strategy reasoning
  ai_analysis: string;           // Full Gemini analysis
  quant_grade: string;           // A, B, C, D, F
  model: string;                 // "gemini-2.5-flash"
  regime_at_exit: {
    regime: string;              // "LONG_GAMMA" or "SHORT_GAMMA"
    net_gex: string;             // Net Gamma Exposure
    spot_price: string;          // SPY spot price
  };
  analyzed_at: Timestamp;        // When analysis was performed
  success: boolean;              // Whether analysis succeeded
}
```

## AI Prompt Engineering

The system prompts Gemini with:

### Trade Context
- Entry/Exit prices and P&L
- Trade direction and quantity
- Original strategy reasoning
- GEX regime at entry/exit

### Analysis Framework
1. **Exit Timing Analysis**
   - Was the exit optimal?
   - Too early or too late?
   - Key signals missed or captured

2. **GEX Regime Alignment**
   - Did the trade align with market structure?
   - LONG_GAMMA: Stabilizing market
   - SHORT_GAMMA: Volatile market

3. **Risk Management Assessment**
   - Position sizing
   - Thesis adherence
   - Risk/reward profile

### Output Format
- **GRADE:** A/B/C/D/F
- **EXECUTIVE SUMMARY:** 2-3 sentence summary
- **DETAILED ANALYSIS:** Breakdown by category
- **ACTIONABLE IMPROVEMENTS:** 3 specific points

## Deployment

### 1. Deploy Cloud Function

```bash
cd functions

# Deploy the journaling function
firebase deploy --only functions:analyze_closed_trade

# Or deploy all functions
firebase deploy --only functions
```

### 2. Environment Variables

Ensure these are set in Firebase Functions configuration:

```bash
firebase functions:config:set \
  vertex_ai.project_id="YOUR_PROJECT_ID" \
  vertex_ai.location="us-central1" \
  vertex_ai.model_id="gemini-2.5-flash"
```

Or use environment variables:
- `VERTEX_AI_PROJECT_ID` or `GOOGLE_CLOUD_PROJECT`
- `VERTEX_AI_LOCATION` (default: `us-central1`)
- `VERTEX_AI_MODEL_ID` (default: `gemini-2.5-flash`)

### 3. Frontend Integration

#### Option A: Full Page Component

```tsx
// src/pages/TradeJournal.tsx
import { TradeJournal } from "@/components/JournalEntry";

export default function TradeJournalPage() {
  return (
    <div className="container mx-auto p-6">
      <TradeJournal />
    </div>
  );
}
```

#### Option B: Dashboard Widget

```tsx
// src/pages/Dashboard.tsx
import { TradeJournalWidget } from "@/components/JournalEntry";

export default function Dashboard() {
  return (
    <div className="grid grid-cols-3 gap-4">
      {/* Other widgets */}
      <TradeJournalWidget />
    </div>
  );
}
```

### 4. Firestore Security Rules

Add to `firestore.rules`:

```javascript
// Trade journal: user can read their own, system can write
match /users/{userId}/tradeJournal/{tradeId} {
  allow read: if request.auth != null && request.auth.uid == userId;
  allow create: if request.auth != null && request.auth.uid == userId;
  allow update, delete: if false; // Immutable
}
```

## Testing

### 1. Trigger Manual Analysis

Close a shadow trade to trigger analysis:

```typescript
// In Firebase Console or via code
db.collection("shadowTradeHistory").doc(tradeId).update({
  status: "CLOSED",
  exit_price: "500.00",
  exit_timestamp: new Date(),
});
```

### 2. Verify in Firestore

Check that journal entry was created:

```
users/{uid}/tradeJournal/{tradeId}
```

Should contain:
- `ai_analysis` (full text)
- `quant_grade` (A-F)
- `success: true`

### 3. View in UI

Navigate to the journal page or widget to see the analysis displayed.

## Monitoring

### Cloud Functions Logs

```bash
# View journaling function logs
firebase functions:log --only analyze_closed_trade

# Or use gcloud
gcloud logging read "resource.type=cloud_function AND resource.labels.function_name=analyze_closed_trade" --limit 50
```

### Firestore Console

Monitor `users/{uid}/tradeJournal` collection for new entries.

### Metrics to Track

- **Analysis Success Rate:** `success: true` vs `success: false`
- **Grade Distribution:** Count of A, B, C, D, F grades
- **Average Response Time:** Gemini API latency
- **Token Usage:** Track Gemini costs

## Grading Rubric

The AI assigns grades based on:

| Grade | Description | Criteria |
|-------|-------------|----------|
| **A** | Excellent | Optimal exit, regime-aligned, strong risk management |
| **B** | Good | Minor timing issues, mostly well-executed |
| **C** | Average | Mixed results, some misalignments |
| **D** | Poor | Significant mistakes, poor timing or regime fit |
| **F** | Fail | Major errors, ignored risk management |

## Cost Estimation

### Gemini 2.5 Flash Pricing (as of Dec 2024)

- **Input tokens:** ~$0.00025 per 1K tokens
- **Output tokens:** ~$0.00075 per 1K tokens

**Per Analysis:**
- Input: ~1-2K tokens (trade data + prompt)
- Output: ~500-1K tokens (analysis)
- **Cost per analysis:** ~$0.001-0.002

**Monthly Volume:**
- 100 trades/month = **~$0.10-0.20**
- 1,000 trades/month = **~$1-2**

Very affordable for the value provided!

## Troubleshooting

### Issue: Journal entries not appearing

**Solutions:**
1. Check Cloud Functions logs for errors
2. Verify Vertex AI credentials are configured
3. Ensure `shadowTradeHistory` has correct `uid` field
4. Check Firestore security rules allow writes

### Issue: "N/A" grade displayed

**Solutions:**
1. Check Gemini response format
2. Verify prompt includes "GRADE:" section
3. Review Cloud Functions logs for parsing errors

### Issue: Analysis fails with error

**Solutions:**
1. Check Vertex AI quota limits
2. Verify project has Vertex AI API enabled
3. Ensure service account has necessary permissions
4. Review error message in journal entry

### Issue: UI not updating in real-time

**Solutions:**
1. Check Firebase authentication
2. Verify Firestore rules allow reads
3. Check browser console for errors
4. Ensure WebSocket connection is active

## Future Enhancements

Potential features to add:

- [ ] Historical grade trends chart
- [ ] Compare trades by symbol
- [ ] Export journal to PDF
- [ ] Custom analysis prompts
- [ ] Multi-model analysis (GPT-4, Claude, etc.)
- [ ] Regime snapshots at entry time
- [ ] Trade replay with regime overlay
- [ ] Peer comparison (anonymous)
- [ ] Weekly performance summary email
- [ ] Integration with trading notes

## Example Output

### Sample Analysis

```
GRADE: B

EXECUTIVE SUMMARY:
Solid trade execution with good entry timing. Exit was slightly premature, 
leaving ~$50 on the table as SPY continued its rally. Trade aligned well 
with LONG_GAMMA regime, showing good regime awareness.

DETAILED ANALYSIS:

Exit Timing: The exit at $498.50 was reasonable but premature. Technical 
indicators showed continued momentum, and the LONG_GAMMA regime suggested 
the rally would be dampened rather than reversed. Holding for another 
30-60 minutes could have captured an additional 0.3% gain.

GEX Regime Fit: Excellent alignment. Entering a LONG position during 
LONG_GAMMA regime was appropriate, as dealer hedging would dampen downside 
moves. The trade showed strong regime awareness.

Risk Management: Position size at 2.5% of portfolio was prudent. The quick 
exit suggests possibly too-tight stop loss or lack of confidence in the 
thesis. Consider widening stops in stabilizing regimes.

ACTIONABLE IMPROVEMENTS:
1. In LONG_GAMMA regimes, give trades more breathing room. Consider 
   widening stops by 20-30% to avoid premature exits.
2. Set profit targets before entry. A pre-defined target at $500 would 
   have captured the full move.
3. Use trailing stops in trending markets to lock in gains while staying 
   in the trade longer.
```

## Support

For questions or issues:
1. Check this documentation
2. Review Cloud Functions logs
3. Verify Vertex AI configuration
4. Check Firestore security rules

---

**Last Updated:** December 30, 2025  
**Version:** 1.0  
**Status:** Production Ready ✅
