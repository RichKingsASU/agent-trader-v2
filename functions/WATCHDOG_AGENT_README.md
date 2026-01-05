# Operational Watchdog Agent

## Overview

The Operational Watchdog Agent is an autonomous monitoring system that detects anomalous trading behavior in real-time and automatically protects users by shutting down trading when dangerous patterns are detected.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Operational Watchdog Agent                      │
│                                                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   Anomaly    │  │ Kill-Switch  │  │    Alert     │           │
│  │  Detection   │─▶│  Activation  │─▶│    System    │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│         │                  │                  │                   │
│         ▼                  ▼                  ▼                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │   Gemini AI  │  │  Firestore   │  │  Dashboard   │           │
│  │Explainability│  │ trading_enabled│  │   Alerts     │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
└──────────────────────────────────────────────────────────────────┘
```

## Features

### 1. **Anomaly Detection**

The watchdog monitors three types of anomalous behavior:

#### A. Losing Streak Detection
- **Trigger**: 5+ consecutive losing trades within 10 minutes
- **Severity**: CRITICAL
- **Action**: Immediate kill-switch activation
- **Example**: 
  ```
  Agent shut down because Strategy X had 5 consecutive losing trades 
  totaling $500 loss within 10 minutes during a -2.5% market slide.
  ```

#### B. Rapid Drawdown Detection
- **Trigger**: >5% portfolio loss within 10 minutes
- **Severity**: HIGH
- **Action**: Immediate kill-switch activation
- **Example**:
  ```
  Agent shut down because portfolio lost 5.2% ($1,250) across 8 trades 
  in 10 minutes, exceeding safety threshold.
  ```

#### C. Market Condition Mismatch
- **Trigger**: Multiple BUY trades during bearish market (Negative GEX)
- **Severity**: MEDIUM (Warning)
- **Action**: Log warning (no kill-switch)
- **Example**:
  ```
  Warning: Strategy executing 3 BUY trades during bearish regime 
  (Negative GEX = -$1.2M). May indicate strategy malfunction.
  ```

### 2. **Automatic Kill-Switch**

When a critical anomaly is detected:

1. **Disable Trading**: Sets `users/{userId}/status/trading.enabled = false`
2. **Record Context**: Stores anomaly type, severity, and timestamp
3. **Audit Trail**: Creates detailed event log

**Firestore Structure**:
```javascript
users/{userId}/status/trading: {
  enabled: false,
  disabled_by: "watchdog",
  disabled_at: Timestamp,
  reason: "5 consecutive losing trades within 10 minutes. Total loss: $500.00",
  anomaly_type: "LOSING_STREAK",
  severity: "CRITICAL",
  explanation: "Agent shut down because..."
}
```

### 3. **High-Priority Alert System**

Alerts are delivered to the user's dashboard at `users/{userId}/alerts/{alertId}`:

```javascript
{
  type: "WATCHDOG_KILL_SWITCH",
  severity: "CRITICAL",
  title: "Trading Halted: LOSING_STREAK",
  message: "Agent shut down because Strategy X had 5 consecutive losing trades...",
  anomaly_type: "LOSING_STREAK",
  anomaly_description: "Detected 5 consecutive losing trades within 10 minutes...",
  metadata: {
    consecutive_losses: 5,
    losing_trade_ids: ["trade1", "trade2", ...],
    total_loss_usd: "500.00",
    time_window_minutes: 10
  },
  created_at: Timestamp,
  read: false,
  acknowledged: false,
  priority: "HIGH"
}
```

### 4. **AI-Powered Explainability**

Uses Gemini (Vertex AI) to generate human-readable explanations:

**Prompt Structure**:
```
You are an AI trading risk analyst. Explain why the automated watchdog 
system shut down trading.

Anomaly Detected:
- Type: LOSING_STREAK
- Severity: CRITICAL
- Description: Detected 5 consecutive losing trades within 10 minutes. 
  Total loss: $500.00

Recent Trades (Last 10 minutes):
1. SELL SPY - P&L: -1.2% - Reasoning: Market momentum shifted
2. BUY QQQ - P&L: -0.8% - Reasoning: Tech sector strength
...

Market Context:
SPY Net GEX: -$1,200,000, Market Bias: Bearish

Task: Write a clear, concise explanation (2-3 sentences) explaining:
1. What pattern triggered the shutdown
2. Why this pattern is dangerous
3. What market conditions contributed to the issue

Start with "Agent shut down because..."
```

**Example Output**:
```
Agent shut down because Strategy X executed 5 consecutive losing trades 
totaling $500 within 10 minutes, indicating a systematic failure to adapt 
to market conditions. This pattern is dangerous because it suggests the 
strategy is fighting against a bearish market regime (Negative GEX = -$1.2M), 
which can lead to accelerating losses. The automated shutdown prevents 
further capital erosion while you investigate the strategy malfunction.
```

### 5. **Audit Trail**

All watchdog events are logged at `users/{userId}/watchdog_events/{eventId}`:

```javascript
{
  user_id: "user123",
  anomaly_detected: true,
  anomaly_type: "LOSING_STREAK",
  severity: "CRITICAL",
  description: "Detected 5 consecutive losing trades...",
  explanation: "Agent shut down because...",
  metadata: {
    consecutive_losses: 5,
    losing_trade_ids: [...],
    total_loss_usd: "500.00"
  },
  kill_switch_activated: true,
  timestamp: Timestamp
}
```

## Configuration

### Thresholds (Configurable in `watchdog.py`)

```python
# Losing Streak Detection
LOSING_STREAK_THRESHOLD = 5  # Number of consecutive losing trades
LOSING_STREAK_TIME_WINDOW_MINUTES = 10  # Time window
MIN_LOSS_PERCENT = Decimal("0.5")  # Minimum loss % to count (50 bps)

# Rapid Drawdown Detection
RAPID_DRAWDOWN_THRESHOLD = Decimal("5.0")  # 5% loss threshold
```

## Deployment

### 1. Deploy Cloud Function

The watchdog runs as a scheduled Cloud Function:

```bash
# Deploy with Gemini AI support
gcloud functions deploy operational_watchdog \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=. \
  --entry-point=operational_watchdog \
  --trigger-schedule="* * * * *" \
  --set-env-vars VERTEX_AI_LOCATION=us-central1 \
  --max-instances=10 \
  --timeout=540s
```

### 2. Grant Vertex AI Permissions

```bash
# Grant Vertex AI User role to Cloud Functions service account
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_PROJECT_ID@appspot.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

### 3. Enable Required APIs

```bash
gcloud services enable aiplatform.googleapis.com
gcloud services enable firestore.googleapis.com
```

## Usage

### Monitoring Dashboard Integration

Frontend components can listen to alerts and watchdog events:

```typescript
// Listen to high-priority alerts
const alertsRef = collection(
  db, 
  "users", 
  userId, 
  "alerts"
);

const alertsQuery = query(
  alertsRef,
  where("priority", "==", "HIGH"),
  where("read", "==", false),
  orderBy("created_at", "desc")
);

onSnapshot(alertsQuery, (snapshot) => {
  snapshot.forEach((doc) => {
    const alert = doc.data();
    if (alert.type === "WATCHDOG_KILL_SWITCH") {
      showCriticalAlert(alert);
    }
  });
});
```

### Manual Override

Users can manually re-enable trading after reviewing the alert:

```typescript
const enableTrading = httpsCallable(functions, 'enable_trading_manually');
const result = await enableTrading({ 
  acknowledge_risk: true,
  override_reason: "Reviewed anomaly, strategy updated"
});
```

## Testing

### Unit Tests

```bash
# Test anomaly detection
pytest functions/tests/test_watchdog.py -v

# Test specific scenarios
pytest functions/tests/test_watchdog.py::test_losing_streak_detection -v
pytest functions/tests/test_watchdog.py::test_rapid_drawdown_detection -v
pytest functions/tests/test_watchdog.py::test_market_condition_mismatch -v
```

### Manual Testing

```python
# Create test scenario: 5 losing trades
from functions.utils.watchdog import monitor_user_trades
from google.cloud import firestore

db = firestore.Client()

# Monitor specific user
result = await monitor_user_trades(db=db, user_id="test_user_123")

print(f"Status: {result['status']}")
if result['status'] == 'KILL_SWITCH_ACTIVATED':
    print(f"Anomaly: {result['anomaly_type']}")
    print(f"Explanation: {result['explanation']}")
```

## Monitoring & Observability

### Cloud Logging Queries

```
# View all watchdog events
resource.type="cloud_function"
resource.labels.function_name="operational_watchdog"
severity>=WARNING

# View kill-switch activations
resource.type="cloud_function"
resource.labels.function_name="operational_watchdog"
jsonPayload.message=~"KILL-SWITCH ACTIVATED"

# View anomalies by type
resource.type="cloud_function"
resource.labels.function_name="operational_watchdog"
jsonPayload.anomaly_type="LOSING_STREAK"
```

### Firestore Monitoring

Check global watchdog status:

```javascript
// Read: ops/watchdog_status
{
  last_sweep_at: Timestamp,
  users_monitored: 42,
  kill_switches_activated: 2,
  warnings_detected: 5,
  errors: 0
}
```

## Performance

- **Execution Time**: ~2-5 seconds per user (Gemini call: ~1-2 seconds)
- **Frequency**: Every minute
- **Firestore Reads**: ~3-5 reads per user (trades + status + market regime)
- **Firestore Writes**: 2-4 writes per anomaly (status + alert + event log)
- **Vertex AI Calls**: 1 per critical anomaly (only when kill-switch triggered)

### Cost Estimate

Assuming 100 active users:
- **Cloud Functions**: ~$0.10/day (60 minutes × 24 hours × 100 users)
- **Firestore Reads**: ~$0.15/day (4 reads/user × 1440 minutes × 100 users)
- **Firestore Writes**: ~$0.05/day (assuming 5 anomalies/day)
- **Vertex AI (Gemini)**: ~$0.02/day (5 calls/day × $0.004/call)
- **Total**: ~$0.32/day = ~$10/month for 100 users

## Security

### Multi-Tenant Isolation

- Each user's trades are stored at `users/{userId}/shadowTradeHistory`
- Kill-switch is per-user: `users/{userId}/status/trading.enabled`
- Alerts are user-scoped: `users/{userId}/alerts/{alertId}`
- No cross-user data leakage

### Firestore Rules

```javascript
// Watchdog can write to all user documents (system privilege)
// Users can only read their own alerts
match /users/{userId}/alerts/{alertId} {
  allow read: if request.auth.uid == userId;
  allow write: if false;  // Only system can write
}

match /users/{userId}/watchdog_events/{eventId} {
  allow read: if request.auth.uid == userId;
  allow write: if false;  // Only system can write
}
```

## Troubleshooting

### Watchdog Not Triggering

1. **Check Cloud Scheduler**: 
   ```bash
   gcloud scheduler jobs describe operational_watchdog
   ```

2. **Check Cloud Function Logs**:
   ```bash
   gcloud functions logs read operational_watchdog --limit 50
   ```

3. **Verify Trades Exist**:
   ```bash
   # Check if user has recent shadow trades
   firebase firestore:get users/USER_ID/shadowTradeHistory
   ```

### Gemini AI Not Working

1. **Check Vertex AI Permissions**:
   ```bash
   gcloud projects get-iam-policy YOUR_PROJECT_ID \
     --flatten="bindings[].members" \
     --filter="bindings.role:roles/aiplatform.user"
   ```

2. **Test Gemini API Directly**:
   ```python
   import vertexai
   from vertexai.generative_models import GenerativeModel
   
   vertexai.init(project="YOUR_PROJECT", location="us-central1")
   model = GenerativeModel("gemini-2.0-flash-exp")
   response = model.generate_content("Hello!")
   print(response.text)
   ```

3. **Use Fallback Explanation**: If Gemini fails, the watchdog automatically generates a fallback explanation without AI.

### False Positives

If the watchdog is too sensitive:

1. **Adjust Thresholds** in `watchdog.py`:
   ```python
   LOSING_STREAK_THRESHOLD = 7  # Increase from 5
   MIN_LOSS_PERCENT = Decimal("1.0")  # Increase from 0.5%
   RAPID_DRAWDOWN_THRESHOLD = Decimal("7.0")  # Increase from 5.0%
   ```

2. **Increase Time Window**:
   ```python
   LOSING_STREAK_TIME_WINDOW_MINUTES = 15  # Increase from 10
   ```

3. **Redeploy**:
   ```bash
   gcloud functions deploy operational_watchdog --source=.
   ```

## Roadmap

### Phase 1 (Current)
- ✅ Losing streak detection
- ✅ Rapid drawdown detection
- ✅ Market condition mismatch detection
- ✅ Automatic kill-switch
- ✅ Gemini AI explainability
- ✅ High-priority alerts

### Phase 2 (Future)
- [ ] Strategy-specific thresholds (different limits per strategy)
- [ ] Adaptive thresholds (ML-based anomaly detection)
- [ ] Automated strategy parameter tuning
- [ ] Integration with external market data feeds
- [ ] SMS/Email alert delivery
- [ ] Slack/Discord webhook integration

### Phase 3 (Future)
- [ ] Predictive anomaly detection (prevent before happening)
- [ ] Strategy backtesting auto-trigger on anomaly
- [ ] Automatic strategy rollback on repeated anomalies
- [ ] Cross-user anomaly correlation analysis
- [ ] Regulatory compliance reporting

## Support

For issues or questions:
1. Check logs: `gcloud functions logs read operational_watchdog`
2. Review Firestore: `ops/watchdog_status` and `users/{userId}/watchdog_events`
3. Test locally: `pytest functions/tests/test_watchdog.py`
4. Review this documentation

## License

Copyright 2024 AgentTrader. All rights reserved.
