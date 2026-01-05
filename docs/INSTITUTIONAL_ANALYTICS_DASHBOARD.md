# Institutional Analytics Dashboard

## Overview

The Institutional Analytics Dashboard is a premium feature that provides deep, actionable insights into trading performance, market structure, and execution quality. This goes **beyond simple P&L** to reveal **why** you're making or losing money—a massive selling point for SaaS.

## Features

### 1. GEX Visualization (Gamma Map) 📊

**Real-time gamma exposure analysis showing Call/Put walls and market regime.**

#### What is GEX?
Gamma Exposure (GEX) measures the aggregate gamma positioning of market makers in options. It provides insights into:
- Market volatility expectations
- Potential price support/resistance levels
- Market maker hedging behavior

#### Key Metrics:
- **Net GEX**: Total gamma exposure (positive = Long Gamma, negative = Short Gamma)
- **Call Wall**: Strike with highest call open interest (potential resistance)
- **Put Wall**: Strike with highest put open interest (potential support)
- **Market Regime**:
  - **Long Gamma** (Net GEX > 0): Market makers dampen volatility → Range-bound trading
  - **Short Gamma** (Net GEX < 0): Market makers amplify volatility → Trending moves

#### Visualization:
- Interactive bar chart showing GEX by strike price
- Color-coded strikes (green for calls, red for puts)
- Reference lines for spot price and gamma walls
- Strike-by-strike breakdown with open interest

#### API Endpoint:
```
GET /api/institutional/gex/{symbol}?tenant_id={tenant_id}
```

#### Response Example:
```json
{
  "symbol": "SPY",
  "spot_price": 450.25,
  "net_gex": 2500000000.00,
  "call_gex_total": 3000000000.00,
  "put_gex_total": -500000000.00,
  "regime": "LONG_GAMMA",
  "regime_description": "LONG GAMMA: Market makers' hedging dampens price movements...",
  "strikes": [...],
  "call_wall": 455.00,
  "put_wall": 445.00,
  "timestamp": "2024-12-30T10:30:00Z",
  "strikes_analyzed": 42
}
```

---

### 2. Sentiment Heatmap 🧠

**AI-powered sentiment analysis using Gemini 1.5 Flash for multiple tickers.**

#### What is Sentiment Analysis?
Uses Google's Gemini 1.5 Flash LLM to analyze news headlines and assess their impact on company fundamentals and cash flows. This goes beyond simple positive/negative sentiment to provide actionable insights.

#### Key Metrics:
- **Sentiment Score**: -1.0 (very bearish) to +1.0 (very bullish)
- **Confidence**: AI's confidence in its analysis (0-100%)
- **Cash Flow Impact**: Analysis of how news affects future cash generation
- **Action**: AI-recommended action (BUY, SELL, HOLD)
- **Reasoning**: Detailed explanation of the analysis

#### Color Scale:
- **Dark Green**: Very Bullish (>0.7)
- **Light Green**: Bullish (0.3 to 0.7)
- **Yellow**: Neutral (-0.3 to 0.3)
- **Orange**: Bearish (-0.7 to -0.3)
- **Red**: Very Bearish (<-0.7)
- **Opacity**: Indicates confidence (higher = more confident)

#### Features:
- Interactive heatmap grid
- Click to re-analyze with latest news
- Detailed tooltips with reasoning and cash flow impact
- Real-time updates

#### API Endpoints:
```
GET /api/institutional/sentiment/heatmap?tenant_id={tenant_id}&symbols={symbols}
POST /api/institutional/sentiment/analyze/{symbol}?tenant_id={tenant_id}
```

#### Response Example:
```json
{
  "tickers": [
    {
      "symbol": "AAPL",
      "sentiment_score": 0.85,
      "confidence": 0.92,
      "action": "BUY",
      "reasoning": "Strong positive sentiment driven by...",
      "cash_flow_impact": "Expected 15% increase in revenue...",
      "news_count": 12,
      "last_analyzed": "2024-12-30T10:25:00Z",
      "color": "hsl(120, 92%, 40%)"
    }
  ],
  "timestamp": "2024-12-30T10:30:00Z",
  "total_analyzed": 10
}
```

---

### 3. Execution Audit 🎯

**Slippage analysis showing the difference between intended and actual fill prices.**

#### What is Slippage?
Slippage is the difference between the intended price and the actual execution price. It's a critical metric for understanding execution quality and hidden trading costs.

#### Key Metrics:
- **Slippage (bps)**: Measured in basis points (100 bps = 1%)
- **$ Impact**: Dollar cost/savings from slippage
- **Time to Fill**: How long it took to execute the order
- **Quality Grades**:
  - Excellent: < -10 bps (you saved money!)
  - Good: -10 to 0 bps
  - Fair: 0 to 10 bps
  - Poor: 10 to 25 bps
  - Bad: > 25 bps

#### Understanding Slippage:
- **Negative slippage** (green): Better than expected → You saved money!
  - Buy: Executed below intended price
  - Sell: Executed above intended price
- **Positive slippage** (red): Worse than expected → Cost of execution
  - Buy: Paid more than intended
  - Sell: Received less than intended

#### Features:
- Sortable table with all executions
- Filter by symbol and time period
- Summary statistics (avg, median, worst, best)
- Total slippage cost tracking
- Average fill time monitoring

#### API Endpoint:
```
GET /api/institutional/execution/audit?tenant_id={tenant_id}&days={days}&symbol={symbol}
```

#### Response Example:
```json
{
  "executions": [
    {
      "trade_id": "uuid",
      "timestamp": "2024-12-30T10:15:00Z",
      "symbol": "AAPL",
      "side": "buy",
      "quantity": 100,
      "intended_price": 150.00,
      "executed_price": 149.95,
      "slippage_dollars": -0.05,
      "slippage_bps": -3.33,
      "slippage_percent": -0.0333,
      "order_type": "limit",
      "time_to_fill_ms": 250,
      "strategy_id": "uuid",
      "status": "filled"
    }
  ],
  "total_executions": 150,
  "avg_slippage_bps": -2.5,
  "median_slippage_bps": -1.8,
  "worst_slippage_bps": 15.2,
  "best_slippage_bps": -12.4,
  "total_slippage_cost": -125.50,
  "avg_time_to_fill_ms": 325.0,
  "timestamp": "2024-12-30T10:30:00Z"
}
```

---

## Technical Implementation

### Backend

#### Files Created:
- `/workspace/backend/analytics/institutional_api.py` - FastAPI router with all endpoints

#### Integration:
Added to `/workspace/backend/strategy_service/app.py`:
```python
from backend.analytics.institutional_api import router as institutional_router
app.include_router(institutional_router)
```

#### Dependencies:
- Existing GEX engine: `/workspace/functions/utils/gex_engine.py`
- Existing sentiment strategy: `/workspace/backend/strategy_engine/strategies/llm_sentiment_alpha.py`
- Firestore for data storage
- Alpaca API for options data
- Google Vertex AI (Gemini 1.5 Flash) for sentiment analysis

### Frontend

#### Files Created:
- `/workspace/frontend/src/pages/Analytics.tsx` - Main dashboard page
- `/workspace/frontend/src/components/institutional/GEXVisualization.tsx` - GEX component
- `/workspace/frontend/src/components/institutional/SentimentHeatmap.tsx` - Sentiment component
- `/workspace/frontend/src/components/institutional/ExecutionAudit.tsx` - Execution audit component

#### Integration:
1. Added route to `/workspace/frontend/src/App.tsx`:
   ```tsx
   <Route path="/analytics" element={<Analytics />} />
   ```

2. Added navigation link to `/workspace/frontend/src/components/AppSidebar.tsx`:
   ```tsx
   { title: "Analytics", url: "/analytics", icon: BarChart3 }
   ```

#### UI Components Used:
- Recharts for data visualization
- Shadcn/ui for UI components
- Lucide icons
- Tailwind CSS for styling

---

## Usage

### Accessing the Dashboard

Navigate to: **http://localhost:5173/analytics**

Or click "Analytics" in the sidebar navigation.

### Configuration

The dashboard allows you to configure:
1. **Tenant ID**: Your tenant identifier for multi-tenant setups
2. **GEX Symbol**: Which symbol to analyze for gamma exposure (default: SPY)

### Default Symbols for Sentiment Analysis
- SPY, QQQ, AAPL, TSLA, NVDA, MSFT, GOOGL, AMZN, META, AMD

You can customize this list in the component props.

---

## SaaS Value Proposition

### Why This Matters 💰

Traditional trading platforms only show P&L, but institutional traders need to understand:
1. **WHY** they're making or losing money
2. **WHAT** market forces are affecting their trades
3. **HOW** well their orders are being executed

### Competitive Advantages

#### 1. Market Structure Insights
- GEX analysis reveals hidden market dynamics
- Professional traders pay $500-5000/month for this data
- We calculate it in real-time from Alpaca options data

#### 2. AI-Powered Intelligence
- Gemini 1.5 Flash provides institutional-grade fundamental analysis
- Goes beyond sentiment to analyze cash flow impact
- Scalable to hundreds of tickers

#### 3. Execution Transparency
- Most platforms hide execution costs
- We show exactly how much each trade costs in slippage
- Critical for algorithmic trading optimization

### Pricing Tiers

Suggested SaaS pricing:
- **Basic**: P&L only ($49/month)
- **Professional**: + GEX + Execution Audit ($149/month)
- **Institutional**: + Sentiment Analysis ($499/month)

---

## Development Notes

### Running the Backend

1. Ensure backend service is running:
   ```bash
   cd /workspace/backend
   uvicorn strategy_service.app:app --reload --port 8001
   ```

2. Set environment variables:
   ```bash
   export ALPACA_API_KEY_ID="your_key"
   export ALPACA_API_SECRET_KEY="your_secret"
   export GOOGLE_APPLICATION_CREDENTIALS="path/to/credentials.json"
   ```

### Running the Frontend

```bash
cd /workspace/frontend
npm run dev
```

Navigate to: http://localhost:5173/analytics

### Testing

1. **GEX Endpoint**:
   ```bash
   curl "http://localhost:8001/api/institutional/gex/SPY?tenant_id=demo-tenant"
   ```

2. **Sentiment Endpoint**:
   ```bash
   curl "http://localhost:8001/api/institutional/sentiment/heatmap?tenant_id=demo-tenant&symbols=SPY,AAPL"
   ```

3. **Execution Audit**:
   ```bash
   curl "http://localhost:8001/api/institutional/execution/audit?tenant_id=demo-tenant&days=7"
   ```

### Data Requirements

#### For GEX:
- Alpaca options data access
- Active market hours for real-time data

#### For Sentiment:
- News data in Firestore: `tenants/{tenant_id}/news`
- Vertex AI credentials
- Gemini 1.5 Flash API access

#### For Execution Audit:
- Trade data in Firestore: `tenants/{tenant_id}/ledger_trades`
- Fields required: `intended_price`, `price`, `side`, `qty`, `timestamp`

---

## Future Enhancements

### Phase 2
- [ ] Historical GEX trends and regime changes
- [ ] Multi-symbol GEX comparison
- [ ] GEX-based trading signals

### Phase 3
- [ ] Sentiment backtesting
- [ ] Sentiment-based portfolio optimization
- [ ] Custom sentiment models

### Phase 4
- [ ] Execution quality benchmarking
- [ ] Broker comparison
- [ ] Smart order routing recommendations

### Phase 5
- [ ] Export analytics to PDF/Excel
- [ ] Email alerts for regime changes
- [ ] Slack/Discord integrations

---

## Troubleshooting

### GEX Not Loading
- Check Alpaca API credentials
- Verify market hours (options data only during trading hours)
- Ensure symbol has liquid options (SPY, QQQ work best)

### Sentiment Analysis Empty
- Check Firestore for news data in correct collection
- Verify Vertex AI credentials
- Check Gemini 1.5 Flash API quota

### Execution Audit Empty
- Check that trades exist in Firestore `ledger_trades` collection
- Verify `intended_price` field is populated
- Check date range (default: last 7 days)

### CORS Errors
- Ensure backend has CORS middleware enabled
- Check backend URL in frontend components (default: http://localhost:8001)

---

## Credits

**Built with:**
- Google Gemini 1.5 Flash (AI sentiment analysis)
- Alpaca Markets (options data)
- Recharts (data visualization)
- Shadcn/ui (UI components)
- FastAPI (backend)
- React + TypeScript (frontend)

**Developed by:** AgentTrader Team
**Date:** December 30, 2024
**Version:** 1.0.0
