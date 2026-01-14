# Analytics Engine

The Analytics Engine provides comprehensive trade analysis, system monitoring, and performance tracking for the AgentTrader platform.

## Features

### 1. Trade Parser
Aggregates trades from the `ledger_trades` collection to compute:
- **Daily P&L**: Gross profit, fees, and net profit per day
- **Win/Loss Ratio**: Win rate, loss rate, and trade statistics
- **Performance Metrics**: Best/worst days, most traded symbols, average win/loss

### 2. System Monitor
Tracks system health and performance:
- **API Latency**: Response times for Alpaca and Gemini API calls (avg, p50, p95, p99)
- **Heartbeat Status**: Real-time monitoring with visual indicators (green/yellow/red)
- **Token Usage**: Gemini 2.5 Flash token consumption and cost tracking per user

## Components

### Backend

#### `trade_parser.py`
Core analytics functions for trade performance:

```python
from backend.analytics import compute_daily_pnl, compute_trade_analytics

# Get daily P&L summaries
daily_summaries = compute_daily_pnl(trades, start_date=start, end_date=end)

# Get comprehensive analytics
analytics = compute_trade_analytics(trades)
print(f"Total P&L: ${analytics.total_pnl:.2f}")
print(f"Win Rate: {analytics.overall_win_rate:.1f}%")
```

#### `metrics.py`
System metrics tracking:

```python
from backend.analytics.metrics import get_metrics_tracker, track_api_call

# Track an API call automatically
with track_api_call("alpaca", "/v2/account"):
    account = alpaca_client.get_account()

# Record token usage
tracker = get_metrics_tracker()
tracker.record_token_usage(
    user_id="user123",
    model="gemini-2.5-flash",
    prompt_tokens=1000,
    completion_tokens=500,
)

# Get latency statistics
stats = tracker.get_api_latency_stats("alpaca", minutes=15)
print(f"Average latency: {stats['avg_ms']:.0f}ms")
```

#### `heartbeat.py`
Heartbeat monitoring:

```python
from backend.analytics.heartbeat import check_heartbeat, write_heartbeat

# Check heartbeat status
heartbeat = check_heartbeat(tenant_id, "market_ingest")
print(f"Status: {heartbeat.status}")
print(f"Last seen: {heartbeat.seconds_since_heartbeat}s ago")

# Write a heartbeat (in your service)
write_heartbeat(tenant_id, "market_ingest", status="running")
```

#### `integrations.py`
Easy integration with existing code:

```python
from backend.analytics.integrations import track_alpaca_api, track_gemini_api

# Decorator for Alpaca calls
@track_alpaca_api("/v2/account")
def get_account():
    return alpaca_client.get_account()

# Decorator for Gemini calls
@track_gemini_api(user_id="user123", request_type="signal_generation")
def generate_signal(prompt: str):
    return gemini_model.generate_content(prompt)
```

#### `api.py`
FastAPI endpoints for analytics:

```python
# GET /api/analytics/trade-analytics?tenant_id=xxx&days=30
# Returns: Comprehensive trade analytics

# GET /api/analytics/win-loss-ratio?tenant_id=xxx&days=30
# Returns: Win/loss ratio and metrics

# GET /api/analytics/api-latency/alpaca?minutes=15
# Returns: API latency statistics

# GET /api/analytics/heartbeat/market_ingest?tenant_id=xxx
# Returns: Heartbeat status

# GET /api/analytics/token-usage?user_id=xxx&hours=24
# Returns: Token usage and cost

# GET /api/analytics/system-health?tenant_id=xxx
# Returns: Comprehensive system health snapshot
```

### Frontend

#### `SystemHealth.tsx`
React component for system monitoring dashboard:

```tsx
import { SystemHealth } from "@/components/SystemHealth";

function MonitoringPage() {
  return (
    <div className="container mx-auto p-6">
      <SystemHealth />
    </div>
  );
}
```

Features:
- **API Latency Cards**: Real-time latency metrics for Alpaca and Gemini
- **Heartbeat Monitor**: Visual green/yellow/red status indicator
- **Token Usage Tracker**: Cost tracking for SaaS billing tiers
- **Auto-refresh**: Updates every 15 seconds

## Integration Guide

### Step 1: Add Analytics Router to Backend

In your main FastAPI app:

```python
from backend.analytics.api import router as analytics_router

app = FastAPI()
app.include_router(analytics_router)
```

### Step 2: Track API Calls

#### Option A: Use Decorators (Recommended)

```python
from backend.analytics.integrations import track_alpaca_api, track_gemini_api

@track_alpaca_api("/v2/orders")
def place_order(symbol: str, qty: int):
    return alpaca_client.submit_order(symbol, qty)

@track_gemini_api(user_id="user123")
def generate_signal(market_data: dict):
    prompt = build_prompt(market_data)
    return gemini_model.generate_content(prompt)
```

#### Option B: Manual Recording

```python
from backend.analytics.integrations import record_alpaca_call, record_gemini_call
import time

start = time.time()
try:
    response = gemini_model.generate_content(prompt)
    duration_ms = (time.time() - start) * 1000
    
    usage = response.usage_metadata
    record_gemini_call(
        user_id=user_id,
        endpoint="generate_signal",
        duration_ms=duration_ms,
        prompt_tokens=usage.prompt_token_count,
        completion_tokens=usage.candidates_token_count,
    )
except Exception as e:
    duration_ms = (time.time() - start) * 1000
    record_gemini_call(
        user_id=user_id,
        endpoint="generate_signal",
        duration_ms=duration_ms,
        prompt_tokens=0,
        completion_tokens=0,
        success=False,
        error_message=str(e),
    )
    raise
```

### Step 3: Write Heartbeats

In your background services (cron jobs, workers):

```python
from backend.analytics.heartbeat import write_heartbeat
import time

while True:
    try:
        # Do work...
        write_heartbeat(tenant_id, "market_ingest", status="running")
        time.sleep(30)  # Every 30 seconds
    except Exception as e:
        write_heartbeat(tenant_id, "market_ingest", status="degraded", metadata={
            "error": str(e)
        })
        time.sleep(30)
```

### Step 4: Add SystemHealth to Frontend

```tsx
// In your routes or dashboard
import { SystemHealth } from "@/components/SystemHealth";

<Route path="/monitoring" element={<SystemHealth />} />
```

## Data Models

### DailyPnLSummary
```python
@dataclass
class DailyPnLSummary:
    date: str                    # ISO date (YYYY-MM-DD)
    total_pnl: float            # Net P&L (gross - fees)
    gross_pnl: float            # Gross P&L before fees
    fees: float                 # Total fees paid
    trades_count: int           # Number of closed trades
    winning_trades: int         # Number of profitable trades
    losing_trades: int          # Number of losing trades
    win_rate: float            # Win rate percentage
    avg_win: float             # Average winning trade (net, after fees)
    avg_loss: float            # Average losing trade (net, after fees)
    largest_win: float         # Largest single win
    largest_loss: float        # Largest single loss
    expectancy: float          # Expectancy per trade (net)
    performance_label: str     # "Profitable" | "Flat" | "Losing"
    flat_threshold: float      # +/- band used to call a day "Flat"
    threshold_logic: str       # Human-readable threshold rules
    symbols_traded: List[str]  # List of symbols traded
```

### APICallMetric
```python
@dataclass
class APICallMetric:
    service: str               # "alpaca" or "gemini"
    endpoint: str              # API endpoint called
    duration_ms: float         # Duration in milliseconds
    timestamp: datetime        # When the call occurred
    status: str               # "success", "error", "timeout"
    error_message: Optional[str]  # Error details if failed
```

### TokenUsageMetric
```python
@dataclass
class TokenUsageMetric:
    user_id: str              # User who made the request
    model: str               # "gemini-2.5-flash"
    prompt_tokens: int       # Input tokens
    completion_tokens: int   # Output tokens
    total_tokens: int        # Total tokens used
    timestamp: datetime      # When the call occurred
    request_type: str        # "signal_generation", etc.
    cost_estimate: float     # Estimated cost in USD
```

## Configuration

### Token Pricing
Current rates (as of Dec 2024) for Gemini 2.5 Flash:
- Input: $0.075 per 1M tokens
- Output: $0.30 per 1M tokens

Update in `metrics.py` if rates change:

```python
# In record_token_usage()
cost = (prompt_tokens * 0.075 / 1_000_000) + (completion_tokens * 0.30 / 1_000_000)
```

### Heartbeat Threshold
Default: 120 seconds (2 minutes)

To customize:

```python
heartbeat = check_heartbeat(tenant_id, service_id, stale_threshold_seconds=180)
```

### Metrics Retention
Default: 60 minutes in-memory

For production, consider:
- Prometheus for time-series metrics
- InfluxDB for high-volume data
- Cloud Monitoring (GCP/AWS)

## Testing

Run tests:

```bash
# Test trade parser
pytest tests/test_analytics_trade_parser.py -v

# Test metrics tracking
pytest tests/test_analytics_metrics.py -v

# Test all analytics
pytest tests/test_analytics_*.py -v
```

## Production Considerations

### Scalability
- **In-memory metrics** are limited to single-instance deployments
- For multi-instance/distributed systems, use:
  - Prometheus with pushgateway
  - Cloud Monitoring API
  - Redis for shared metrics state

### Persistence
- Current implementation stores metrics in memory (60min retention)
- For long-term analysis, periodically export to:
  - BigQuery for analytics
  - Cloud Storage for archival
  - Time-series database

### Security
- Token usage data contains sensitive cost information
- Ensure proper authentication on analytics endpoints
- Consider rate limiting on analytics API calls

### Monitoring
Set up alerts for:
- API latency > 2000ms (p95)
- Error rate > 10%
- Heartbeat stale > 120s
- Token costs exceeding budget thresholds

## Future Enhancements

- [ ] Real-time streaming metrics with WebSocket
- [ ] Custom alerting rules and notifications
- [ ] Historical trend analysis
- [ ] Anomaly detection for unusual patterns
- [ ] Cost forecasting and budget alerts
- [ ] Multi-tenant analytics aggregation
- [ ] Export to CSV/Excel for reporting
- [ ] Integration with external monitoring tools

## Support

For questions or issues:
- Check the test files for usage examples
- Review integration examples in `integrations.py`
- Refer to the main ARCHITECTURE docs
