# Quick Start: Institutional SaaS Features

Get up and running with the new institutional features in 5 minutes.

## Prerequisites
- Firebase project configured
- Cloud Functions deployed
- Firestore database initialized
- Node.js and Python environments set up

## Step 1: Deploy Backend (2 minutes)

```bash
# Navigate to functions directory
cd functions

# Install new dependencies (Vertex AI)
pip install -r requirements.txt

# Deploy the trade journal Cloud Function
firebase deploy --only functions:on_trade_closed

# Verify deployment
firebase functions:log --only on_trade_closed
```

## Step 2: Add Sample Data (1 minute)

### Whale Flow Data
```javascript
// In Firebase Console or via script
const db = admin.firestore();

// Add sample unusual activity
await db.collection('marketData').doc('options').collection('unusual_activity').add({
  ticker: 'SPY',
  type: 'Sweep',
  premium: '2500000',  // $2.5M
  strike: '450',
  expiry: '2025-12-31',
  optionType: 'Call',
  side: 'Ask',
  timestamp: admin.firestore.FieldValue.serverTimestamp(),
  volume: 1000,
  spotPrice: '445.50'
});
```

### Sentiment Data
```javascript
// Add sample sector sentiment
await db.collection('marketData').doc('sentiment').collection('sectors').doc('SPY').set({
  sector: 'Technology',
  symbol: 'SPY',
  marketCap: 500,  // $500B
  sentimentScore: 0.75,  // Very Bullish
  change24h: 2.5,
  volume: 100000000,
  aiSummary: 'Strong bullish momentum',
  timestamp: admin.firestore.FieldValue.serverTimestamp()
});
```

## Step 3: Deploy Frontend (2 minutes)

```bash
# Navigate to frontend directory
cd ../frontend

# Install dependencies (if needed)
npm install

# Build and deploy
npm run build
firebase deploy --only hosting

# Or run locally for testing
npm run dev
```

## Step 4: Test Features

### Test Whale Flow Dashboard
1. Navigate to the Whale Flow page
2. Verify the table displays sample data
3. Check the AI analyst summary appears
4. Add more unusual activities and watch real-time updates

### Test Trading Journal
1. Create or update a shadow trade to status CLOSED:
```javascript
// In Firestore
shadowTradeHistory/{tradeId}
{
  status: 'CLOSED',
  exit_price: '450.50',
  realized_pnl: '250.00',
  // ... other fields
}
```
2. Check Cloud Function logs: `firebase functions:log --only on_trade_closed`
3. Verify journal entry created in `users/{uid}/tradeJournal/{tradeId}`
4. View in Trading Journal UI component

### Test Risk Circuit Breakers
1. In your strategy code:
```python
from functions.strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    async def evaluate(self, market_data, account_snapshot, regime_data):
        raw_signal = {
            "action": "BUY",
            "allocation": 0.5,
            "ticker": "SPY",
            "reasoning": "Test signal"
        }
        
        # Apply risk guards
        return self.apply_risk_guards(
            signal=raw_signal,
            account_snapshot=account_snapshot,
            market_data=market_data,
            starting_equity="100000.00"
        )
```
2. Test with different scenarios:
   - Set equity to 98000 (starting 100000) = -2% loss
   - Set VIX to 35 in market_data
   - Propose large position (>20% NAV)
3. Verify guards trigger and modify signals

### Test Sentiment Heatmap
1. Navigate to Sentiment Heatmap page
2. Verify treemap renders with sample data
3. Hover over tiles to see tooltips
4. Click tiles to see detailed analysis
5. Check AI market summary at top

## Step 5: Import Components in Your App

### Add to Main Layout/Router
```tsx
// In your App.tsx or router config
import { WhaleFlow } from "@/components/WhaleFlow";
import { TradingJournal } from "@/components/JournalEntry";
import { SentimentTreemap } from "@/components/SentimentTreemap";

// Add routes
<Route path="/whale-flow" element={<WhaleFlow />} />
<Route path="/journal" element={<TradingJournal />} />
<Route path="/sentiment" element={<SentimentTreemap />} />
```

### Or Use in Dashboard
```tsx
// In your dashboard
<div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
  <WhaleFlow />
  <SentimentTreemap />
</div>

<div className="mt-6">
  <TradingJournal />
</div>
```

## Environment Variables

Add to `.env` or Firebase Functions config:

```bash
# For Gemini AI analysis
VERTEX_AI_PROJECT_ID=your-project-id
VERTEX_AI_LOCATION=us-central1
VERTEX_AI_MODEL_ID=gemini-1.5-flash
```

Set in Firebase:
```bash
firebase functions:config:set \
  vertexai.project_id="your-project-id" \
  vertexai.location="us-central1" \
  vertexai.model_id="gemini-1.5-flash"
```

## Firestore Security Rules

Add to `firestore.rules`:

```javascript
service cloud.firestore {
  match /databases/{database}/documents {
    // Whale Flow - authenticated users can read
    match /marketData/options/unusual_activity/{activity} {
      allow read: if request.auth != null;
      allow write: if false;  // Admin/functions only
    }
    
    // Sentiment Data - authenticated users can read
    match /marketData/sentiment/sectors/{sector} {
      allow read: if request.auth != null;
      allow write: if false;  // Admin/functions only
    }
    
    // Trade Journal - users can read their own
    match /users/{userId}/tradeJournal/{tradeId} {
      allow read: if request.auth.uid == userId;
      allow write: if false;  // Cloud Functions only
    }
    
    // Shadow Trades - users can read/write their own
    match /shadowTradeHistory/{tradeId} {
      allow read, write: if request.auth.uid == resource.data.uid;
    }
  }
}
```

Deploy rules:
```bash
firebase deploy --only firestore:rules
```

## Troubleshooting

### Cloud Function Not Triggering
```bash
# Check function deployment
firebase functions:list | grep on_trade_closed

# View logs
firebase functions:log --only on_trade_closed

# Test trigger manually
# Update a shadowTradeHistory document status to CLOSED
```

### Gemini API Errors
```bash
# Verify Vertex AI API is enabled
gcloud services enable aiplatform.googleapis.com

# Check quotas
gcloud alpha quotas list --filter="service:aiplatform.googleapis.com"

# Test Gemini access
python -c "import vertexai; print('Vertex AI available')"
```

### Real-time Updates Not Working
- Check Firestore connection in browser console
- Verify Firestore rules allow read access
- Check `onSnapshot` errors in console
- Ensure user is authenticated

### Risk Guards Not Applying
- Verify `apply_risk_guards()` is called in strategy
- Check starting_equity is provided
- View logs for guard trigger messages
- Test with extreme values (VIX=50, loss=-10%)

## Performance Tips

1. **Limit Firestore Queries**: Use `.limit(50)` on whale flow and journal queries
2. **Cache AI Results**: Consider caching journal entries for 1 hour
3. **Optimize Treemap**: Limit to top 30 stocks by market cap
4. **Use Indexes**: Create Firestore indexes for common queries

## Next Steps

1. **Customize Risk Thresholds**: Adjust circuit breaker limits in strategy config
2. **Add More Data Sources**: Integrate real unusual activity data feed
3. **Enhance AI Prompts**: Customize Gemini prompts for your trading style
4. **Build Dashboards**: Combine components into comprehensive views
5. **Add Alerts**: Notify users when whale flow or sentiment changes

## Support

For issues or questions:
1. Check logs: `firebase functions:log`
2. Review: `INSTITUTIONAL_SAAS_FEATURES_SUMMARY.md`
3. Test with sample data first
4. Verify all dependencies installed

---

**Congratulations!** 🎉 

You now have four institutional-grade features running:
- ✅ Whale Flow Dashboard
- ✅ Automated Trading Journal
- ✅ Smart Risk Circuit Breakers
- ✅ Sentiment Heatmap

Start trading with confidence! 🚀
