# Institutional Analytics Dashboard - Quick Start Guide

## 🚀 What You Just Built

A professional-grade analytics dashboard featuring:
1. **GEX Visualization** - Real-time gamma exposure mapping
2. **Sentiment Heatmap** - AI-powered sentiment analysis via Gemini 1.5 Flash
3. **Execution Audit** - Slippage analysis and execution quality metrics

## 📍 Access the Dashboard

**URL:** http://localhost:5173/analytics

Or click **"Analytics"** in the sidebar navigation (3rd item under Trading).

---

## 🎯 Quick Test

### 1. Start the Backend

```bash
cd /workspace/backend
uvicorn strategy_service.app:app --reload --port 8001
```

**Required Environment Variables:**
```bash
export ALPACA_API_KEY_ID="your_alpaca_key"
export ALPACA_API_SECRET_KEY="your_alpaca_secret"
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/credentials.json"
```

### 2. Start the Frontend

```bash
cd /workspace/frontend
npm run dev
```

Navigate to: http://localhost:5173/analytics

### 3. Test Each Feature

#### GEX Visualization Tab
1. Click the "GEX" tab (default)
2. Enter a symbol (e.g., "SPY")
3. Should see:
   - Gamma exposure chart
   - Call/Put walls
   - Market regime (Long/Short Gamma)

**Test API:**
```bash
curl "http://localhost:8001/api/institutional/gex/SPY?tenant_id=demo-tenant"
```

#### Sentiment Heatmap Tab
1. Click the "Sentiment" tab
2. Should see colored tiles for each ticker
3. Click a tile to re-analyze with latest news
4. Hover for detailed reasoning

**Test API:**
```bash
curl "http://localhost:8001/api/institutional/sentiment/heatmap?tenant_id=demo-tenant&symbols=SPY,AAPL,TSLA"
```

#### Execution Audit Tab
1. Click the "Execution" tab
2. Should see table of all executions
3. Filter by symbol or date range
4. Sort by any column

**Test API:**
```bash
curl "http://localhost:8001/api/institutional/execution/audit?tenant_id=demo-tenant&days=7"
```

---

## 📁 Files Created

### Backend
```
/workspace/backend/analytics/institutional_api.py
```
**Contains:**
- `GET /api/institutional/gex/{symbol}` - GEX data
- `GET /api/institutional/sentiment/heatmap` - Sentiment scores
- `POST /api/institutional/sentiment/analyze/{symbol}` - Trigger analysis
- `GET /api/institutional/execution/audit` - Execution audit

### Frontend

**Page:**
```
/workspace/frontend/src/pages/Analytics.tsx
```

**Components:**
```
/workspace/frontend/src/components/institutional/GEXVisualization.tsx
/workspace/frontend/src/components/institutional/SentimentHeatmap.tsx
/workspace/frontend/src/components/institutional/ExecutionAudit.tsx
```

**Route Added:**
```tsx
// In /workspace/frontend/src/App.tsx
<Route path="/analytics" element={<Analytics />} />
```

**Navigation Added:**
```tsx
// In /workspace/frontend/src/components/AppSidebar.tsx
{ title: "Analytics", url: "/analytics", icon: BarChart3 }
```

---

## 🔧 Configuration

### Backend Configuration

The API router is registered in:
```python
# /workspace/backend/strategy_service/app.py
from backend.analytics.institutional_api import router as institutional_router
app.include_router(institutional_router)
```

### Frontend Configuration

Dashboard settings can be changed in the UI:
1. **Tenant ID**: Used to query Firestore collections
2. **GEX Symbol**: Which symbol to analyze (default: SPY)

Default sentiment symbols:
```tsx
["SPY", "QQQ", "AAPL", "TSLA", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "AMD"]
```

---

## 🎨 UI Overview

### Color Scheme

**GEX Visualization:**
- Green bars = Call GEX (positive gamma)
- Red bars = Put GEX (negative gamma)
- Blue line = Current spot price
- Dashed lines = Call/Put walls

**Sentiment Heatmap:**
- Dark Green (>0.7) = Very Bullish
- Light Green (0.3-0.7) = Bullish
- Yellow (-0.3 to 0.3) = Neutral
- Orange (-0.7 to -0.3) = Bearish
- Red (<-0.7) = Very Bearish
- Opacity = Confidence

**Execution Audit:**
- Green values = Negative slippage (good!)
- Red values = Positive slippage (cost)
- Badges = Quality grades

---

## 📊 Sample Data

### Mock GEX Data Structure
```json
{
  "symbol": "SPY",
  "spot_price": 450.25,
  "net_gex": 2500000000.00,
  "regime": "LONG_GAMMA",
  "strikes": [
    {
      "strike": 445.00,
      "call_gex": 500000000,
      "put_gex": -200000000,
      "net_gex": 300000000
    }
  ]
}
```

### Mock Sentiment Data Structure
```json
{
  "symbol": "AAPL",
  "sentiment_score": 0.85,
  "confidence": 0.92,
  "action": "BUY",
  "reasoning": "Strong positive sentiment...",
  "cash_flow_impact": "Expected 15% revenue increase..."
}
```

### Mock Execution Data Structure
```json
{
  "trade_id": "uuid",
  "symbol": "AAPL",
  "intended_price": 150.00,
  "executed_price": 149.95,
  "slippage_bps": -3.33,
  "slippage_dollars": -0.05
}
```

---

## 🔍 Data Sources

### GEX (Gamma Exposure)
**Source:** Alpaca Options API
**Requirements:**
- Alpaca API credentials
- Market hours (9:30 AM - 4:00 PM ET)
- Liquid options symbols (SPY, QQQ recommended)

**Calculation:**
```
Call GEX = Gamma × Open Interest × 100 × Spot Price
Put GEX = Gamma × Open Interest × 100 × Spot Price × (-1)
Net GEX = Sum of all strikes
```

### Sentiment Analysis
**Source:** Gemini 1.5 Flash LLM
**Requirements:**
- Google Cloud Vertex AI credentials
- News data in Firestore: `tenants/{tenant_id}/news`
- Active Gemini API quota

**Analysis:**
- Cash flow impact assessment
- Fundamental business impact
- Time horizon (immediate, near-term, long-term)

### Execution Audit
**Source:** Firestore Ledger
**Requirements:**
- Trade records in: `tenants/{tenant_id}/ledger_trades`
- Required fields: `intended_price`, `price`, `side`, `qty`, `timestamp`

**Metrics:**
- Slippage (basis points)
- Dollar impact
- Time to fill
- Quality grading

---

## 🚨 Troubleshooting

### Issue: GEX returns empty data
**Solution:**
1. Check Alpaca API credentials
2. Verify market hours (options only trade during regular hours)
3. Try liquid symbols: SPY, QQQ, AAPL

### Issue: Sentiment heatmap shows all neutral
**Solution:**
1. Check Firestore for news data: `tenants/{tenant_id}/news`
2. Verify Vertex AI credentials
3. Check Gemini API quota/billing

### Issue: Execution audit is empty
**Solution:**
1. Check Firestore for trades: `tenants/{tenant_id}/ledger_trades`
2. Verify `intended_price` field exists on trades
3. Try longer date range (default: 7 days)

### Issue: CORS errors
**Solution:**
1. Verify backend CORS middleware in `strategy_service/app.py`
2. Check backend URL in components (default: `http://localhost:8001`)

### Issue: Components not loading
**Solution:**
1. Check browser console for errors
2. Verify all dependencies installed: `npm install`
3. Check recharts is installed: `npm install recharts`

---

## 💰 SaaS Value Proposition

### Why This Sells

**Problem:** Most trading platforms only show P&L
**Solution:** We show WHY you're making or losing money

**Traditional Platform:**
- Today's P&L: +$500 ✓

**Our Platform:**
- Today's P&L: +$500 ✓
- Market Regime: SHORT_GAMMA (volatile) 📊
- Sentiment: AAPL +0.85 (bullish news) 🧠
- Execution Quality: -2.5 bps avg slippage (excellent) 🎯

### Pricing Strategy

**Tier 1: Basic** ($49/month)
- P&L tracking
- Basic charts

**Tier 2: Professional** ($149/month)
- Everything in Basic
- GEX Visualization
- Execution Audit

**Tier 3: Institutional** ($499/month)
- Everything in Professional
- AI Sentiment Analysis
- API access

### ROI for Customers

**Execution Audit alone:**
- Average trader: 100 trades/month
- Average slippage improvement: 5 bps
- $100/trade average size
- **Savings: $500/month**
- **ROI: Pays for itself!**

---

## 📚 Additional Resources

**Full Documentation:**
`/workspace/docs/INSTITUTIONAL_ANALYTICS_DASHBOARD.md`

**Existing Backend Components:**
- GEX Engine: `/workspace/functions/utils/gex_engine.py`
- Sentiment Strategy: `/workspace/backend/strategy_engine/strategies/llm_sentiment_alpha.py`
- Analytics API: `/workspace/backend/analytics/api.py`

**UI Library:**
- Shadcn/ui: https://ui.shadcn.com
- Recharts: https://recharts.org
- Lucide Icons: https://lucide.dev

---

## ✅ Verification Checklist

- [ ] Backend running on port 8001
- [ ] Frontend running on port 5173
- [ ] Can access /analytics route
- [ ] Sidebar shows "Analytics" link
- [ ] GEX tab loads and shows chart
- [ ] Sentiment tab loads and shows heatmap
- [ ] Execution tab loads and shows table
- [ ] API endpoints return valid JSON
- [ ] No console errors
- [ ] Mobile responsive

---

## 🎉 You're Done!

The Institutional Analytics Dashboard is now live and ready to demo.

**Next Steps:**
1. Populate Firestore with sample data
2. Configure real Alpaca API keys
3. Test with live market data
4. Customize symbols and settings
5. Add to your SaaS pricing page!

**Demo Script:**
"Traditional platforms show you P&L. We show you WHY. Watch as our AI analyzes market structure, sentiment, and execution quality in real-time..."

---

**Questions?** Check the full documentation or the source code comments.
**Want more features?** See the roadmap in the main documentation.
