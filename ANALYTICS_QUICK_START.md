# Analytics Engine - Quick Start Guide

## 🎯 What Was Built

### 1. Trade Parser ✅
**Location**: `backend/analytics/trade_parser.py`

Aggregates the `ledger_trades` collection to calculate:
- **Daily P&L**: Profit/loss per day with FIFO methodology
- **Win/Loss Ratio**: Win rate, loss rate, winning/losing trade counts
- **Performance Stats**: Best/worst days, average wins/losses

```python
from backend.analytics import compute_daily_pnl, compute_win_loss_ratio

# Get daily summaries
summaries = compute_daily_pnl(trades)
for day in summaries:
    print(f"{day.date}: ${day.total_pnl:.2f} | {day.win_rate:.1f}% win rate")

# Get win/loss metrics
metrics = compute_win_loss_ratio(trades)
print(f"Win Rate: {metrics['win_rate']:.1f}%")
```

### 2. System Health Monitor ✅
**Location**: `frontend/src/components/SystemHealth.tsx`

Visual dashboard monitoring:

#### API Latency Tracking
- **Alpaca API**: Response times, error rates, request counts
- **Gemini API**: Latency percentiles (p50, p95, p99)
- **Real-time**: Auto-refresh every 15 seconds

#### Heartbeat Status  
- **Visual Indicator**: Green (healthy) / Yellow (degraded) / Red (down)
- **Threshold**: Alerts if no heartbeat in last 120 seconds
- **Last Seen**: Timestamp and time elapsed display

#### Token Usage Tracking
- **Cost Tracking**: Dollar amount for Gemini 2.5 Flash usage
- **Token Breakdown**: Prompt vs completion tokens
- **Per User**: Tracks individual user consumption
- **SaaS Ready**: Prepared for billing tier implementation

## 🚀 Quick Integration

### Backend Setup (3 steps)

**1. Add Analytics Router**
```python
# In your main FastAPI app
from backend.analytics.api import router as analytics_router

app = FastAPI()
app.include_router(analytics_router)
```

**2. Track API Calls**
```python
# Wrap Gemini calls
from backend.analytics.integrations import track_gemini_api

@track_gemini_api(user_id="user123")
def generate_signal(prompt: str):
    return gemini_model.generate_content(prompt)
```

**3. Write Heartbeats**
```python
# In your background services
from backend.analytics.heartbeat import write_heartbeat

while True:
    # Do work...
    write_heartbeat(tenant_id, "market_ingest", status="running")
    time.sleep(30)  # Every 30 seconds
```

### Frontend Setup (1 step)

**Add the Component**
```tsx
import { SystemHealth } from "@/components/SystemHealth";

function MonitoringPage() {
  return <SystemHealth />;
}
```

## 📊 Available Endpoints

```bash
# Get trade analytics
GET /api/analytics/trade-analytics?tenant_id=xxx&days=30

# Get win/loss ratio
GET /api/analytics/win-loss-ratio?tenant_id=xxx&days=30

# Get API latency
GET /api/analytics/api-latency/alpaca?minutes=15

# Check heartbeat
GET /api/analytics/heartbeat/market_ingest?tenant_id=xxx

# Get token usage
GET /api/analytics/token-usage?user_id=xxx&hours=24

# Get system health
GET /api/analytics/system-health?tenant_id=xxx
```

## 🧪 Testing

```bash
# Run analytics tests
pytest tests/test_analytics_trade_parser.py -v
pytest tests/test_analytics_metrics.py -v

# Manual API test
curl "http://localhost:8080/api/analytics/system-health?tenant_id=test"
```

## 📁 File Structure

```
backend/analytics/
├── __init__.py                  # Exports
├── trade_parser.py             # ⭐ Daily P&L & Win/Loss
├── metrics.py                  # ⭐ API Latency & Token Usage
├── heartbeat.py                # ⭐ Heartbeat Monitoring
├── integrations.py             # Easy integration helpers
├── api.py                      # REST endpoints
├── example_integration.py      # Code examples
└── README.md                   # Full documentation

frontend/src/components/
└── SystemHealth.tsx            # ⭐ Monitoring Dashboard

tests/
├── test_analytics_trade_parser.py
└── test_analytics_metrics.py
```

## 🎨 SystemHealth Component Preview

The dashboard shows:

```
┌─────────────────────────────────────────────────────────┐
│  System Health Monitor                 Updated: 10:45 AM │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │ Alpaca API  │  │ Gemini API  │  │  Heartbeat  │     │
│  │   245ms ✓   │  │   892ms ✓   │  │   HEALTHY   │     │
│  │ P95: 450ms  │  │ P95: 1200ms │  │  🟢 45s ago │     │
│  │ 1.2% errors │  │ 0.5% errors │  │             │     │
│  └─────────────┘  └─────────────┘  └─────────────┘     │
│                                                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │ Gemini 2.5 Flash Token Usage                      │  │
│  │                                                     │  │
│  │   $0.0234 (24h)      234,567 tokens      156 reqs │  │
│  │   ────────────────────────────────────────────    │  │
│  │   Prompt: 189,234 | Completion: 45,333            │  │
│  │                                                     │  │
│  │   💡 SaaS Tier Ready: Track usage for billing     │  │
│  └───────────────────────────────────────────────────┘  │
│                                                           │
│  System Summary:  321 API Calls | 568ms Avg | ✓ Healthy │
└─────────────────────────────────────────────────────────┘
```

## 💰 Token Cost Tracking

Gemini 2.5 Flash rates (Dec 2024):
- **Input**: $0.075 per 1M tokens
- **Output**: $0.30 per 1M tokens

Example costs:
- 1,000 tokens: ~$0.0001
- 10,000 tokens: ~$0.001
- 100,000 tokens: ~$0.01
- 1,000,000 tokens: ~$0.375

## 🔍 Example Trade Analytics Response

```json
{
  "daily_summaries": [
    {
      "date": "2024-12-01",
      "total_pnl": 245.50,
      "gross_pnl": 250.00,
      "fees": 4.50,
      "trades_count": 8,
      "winning_trades": 5,
      "losing_trades": 3,
      "win_rate": 62.5,
      "avg_win": 75.00,
      "avg_loss": -35.00,
      "largest_win": 120.00,
      "largest_loss": -55.00,
      "symbols_traded": ["SPY", "AAPL", "QQQ"]
    }
  ],
  "total_pnl": 245.50,
  "total_trades": 8,
  "overall_win_rate": 62.5,
  "total_winning_trades": 5,
  "total_losing_trades": 3,
  "avg_daily_pnl": 245.50
}
```

## 🛠️ Next Steps

### Immediate (Ready to Use)
- [x] Trade P&L calculations working
- [x] Win/loss ratio tracking working
- [x] API latency monitoring working
- [x] Heartbeat status checks working
- [x] Token usage tracking working
- [x] Frontend dashboard working

### Production Enhancements
- [ ] Add authentication to analytics endpoints
- [ ] Set up rate limiting
- [ ] Migrate to Prometheus/InfluxDB for long-term storage
- [ ] Configure alerts (Slack/email/PagerDuty)
- [ ] Add tracking to existing services:
  - `backend/alpaca_signal_trader.py`
  - `backend/streams/alpaca_quotes_streamer.py`
  - `backend/ingestion/market_data_ingest.py`

## 📚 Documentation

- **Full Docs**: `backend/analytics/README.md`
- **Examples**: `backend/analytics/example_integration.py`
- **Summary**: `ANALYTICS_ENGINE_IMPLEMENTATION.md`
- **This Guide**: `ANALYTICS_QUICK_START.md`

## 🎯 Mission Accomplished

✅ **Trade Parser**: Aggregates trades → Daily P&L & Win/Loss ratio  
✅ **API Latency**: Tracks Alpaca/Gemini response times  
✅ **Heartbeat**: Green/red visual indicator (120s threshold)  
✅ **Token Usage**: Gemini 2.5 Flash cost tracking per user  

**Status**: Production-ready MVP 🚀

---

**Questions?** Check the full documentation in `backend/analytics/README.md`
