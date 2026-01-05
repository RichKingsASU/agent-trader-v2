# Watchdog Agent - Quick Start Guide

## 🚀 Quick Setup (5 minutes)

### 1. Deploy the Watchdog Function

```bash
cd functions

# Deploy with Vertex AI support
gcloud functions deploy operational_watchdog \
  --gen2 \
  --runtime=python311 \
  --region=us-central1 \
  --source=. \
  --entry-point=operational_watchdog \
  --trigger-schedule="* * * * *" \
  --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,VERTEX_AI_LOCATION=us-central1 \
  --max-instances=10 \
  --timeout=540s
```

### 2. Grant Permissions

```bash
# Get your Cloud Functions service account
SERVICE_ACCOUNT=$(gcloud functions describe operational_watchdog \
  --region=us-central1 \
  --format="value(serviceAccountEmail)")

# Grant Vertex AI access for Gemini
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/aiplatform.user"

# Grant Firestore access
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/datastore.user"
```

### 3. Verify Deployment

```bash
# Check if function is deployed
gcloud functions describe operational_watchdog --region=us-central1

# View logs
gcloud functions logs read operational_watchdog --limit 20
```

## 📊 Test the Watchdog

### Option A: Manual Test with Mock Data

```python
# test_watchdog_manual.py
import asyncio
from google.cloud import firestore
from functions.utils.watchdog import monitor_user_trades

async def test():
    db = firestore.Client()
    
    # Create test user with losing trades
    user_id = "test_user_123"
    
    # Add 5 losing trades
    for i in range(5):
        db.collection("users").document(user_id).collection("shadowTradeHistory").add({
            "symbol": "SPY",
            "action": "BUY",
            "side": "BUY",
            "quantity": 10,
            "entry_price": "450.00",
            "current_price": "447.00",  # Losing position
            "current_pnl": "-30.00",
            "pnl_percent": "-0.67",
            "status": "OPEN",
            "created_at": firestore.SERVER_TIMESTAMP,
        })
    
    # Run watchdog
    result = await monitor_user_trades(db=db, user_id=user_id)
    
    print(f"Status: {result['status']}")
    if result['status'] == 'KILL_SWITCH_ACTIVATED':
        print(f"✅ Kill-switch triggered!")
        print(f"Anomaly: {result['anomaly_type']}")
        print(f"Explanation: {result['explanation']}")
    else:
        print(f"❌ Kill-switch not triggered. Result: {result}")

# Run test
asyncio.run(test())
```

### Option B: Trigger via Cloud Scheduler

```bash
# Manually trigger the scheduled function
gcloud scheduler jobs run operational_watchdog --location=us-central1

# View results in logs
gcloud functions logs read operational_watchdog --limit 50
```

## 🎯 Expected Behavior

### Scenario 1: Losing Streak Detected

**Input**: 5 consecutive losing trades within 10 minutes

**Expected Output**:
```json
{
  "status": "KILL_SWITCH_ACTIVATED",
  "anomaly_type": "LOSING_STREAK",
  "severity": "CRITICAL",
  "description": "Detected 5 consecutive losing trades within 10 minutes. Total loss: $500.00",
  "explanation": "Agent shut down because Strategy X had 5 consecutive losing trades totaling $500 within 10 minutes...",
  "alert_id": "alert_abc123",
  "event_id": "event_xyz789"
}
```

**Firestore Changes**:
1. `users/{userId}/status/trading.enabled` = `false`
2. New alert created at `users/{userId}/alerts/{alertId}`
3. New event logged at `users/{userId}/watchdog_events/{eventId}`

### Scenario 2: All Clear

**Input**: No anomalous patterns detected

**Expected Output**:
```json
{
  "status": "ALL_CLEAR",
  "message": "No anomalies detected",
  "trades_analyzed": 3
}
```

**Firestore Changes**: None

## 📱 Frontend Integration

### Listen to Alerts

```typescript
// React component
import { collection, query, where, onSnapshot } from 'firebase/firestore';

function WatchdogAlerts({ userId }) {
  const [alerts, setAlerts] = useState([]);

  useEffect(() => {
    const alertsRef = collection(db, "users", userId, "alerts");
    const alertsQuery = query(
      alertsRef,
      where("type", "==", "WATCHDOG_KILL_SWITCH"),
      where("read", "==", false)
    );

    const unsubscribe = onSnapshot(alertsQuery, (snapshot) => {
      const newAlerts = snapshot.docs.map(doc => ({
        id: doc.id,
        ...doc.data()
      }));
      setAlerts(newAlerts);
      
      // Show critical notification
      if (newAlerts.length > 0) {
        showCriticalNotification(newAlerts[0]);
      }
    });

    return () => unsubscribe();
  }, [userId]);

  return (
    <div className="watchdog-alerts">
      {alerts.map(alert => (
        <Alert key={alert.id} severity="error">
          <AlertTitle>{alert.title}</AlertTitle>
          <AlertDescription>{alert.message}</AlertDescription>
        </Alert>
      ))}
    </div>
  );
}
```

### Check Trading Status

```typescript
// Check if trading is enabled
const tradingStatusRef = doc(db, "users", userId, "status", "trading");

onSnapshot(tradingStatusRef, (doc) => {
  if (doc.exists()) {
    const status = doc.data();
    if (!status.enabled) {
      console.log("Trading disabled by:", status.disabled_by);
      console.log("Reason:", status.reason);
      console.log("Explanation:", status.explanation);
    }
  }
});
```

### Manual Re-Enable (Future)

```typescript
// Create Cloud Function to manually re-enable trading
const enableTrading = httpsCallable(functions, 'enable_trading_manually');

const handleReEnable = async () => {
  const result = await enableTrading({
    userId: currentUser.uid,
    acknowledge_risk: true,
    override_reason: "Reviewed watchdog alert, updated strategy parameters"
  });
  
  if (result.data.success) {
    console.log("Trading re-enabled");
  }
};
```

## 🔍 Monitoring

### View Recent Watchdog Events

```bash
# Query Firestore for recent events
firebase firestore:get users/USER_ID/watchdog_events --limit 10

# View specific event
firebase firestore:get users/USER_ID/watchdog_events/EVENT_ID
```

### View Global Watchdog Status

```bash
# Check overall watchdog health
firebase firestore:get ops/watchdog_status
```

Expected output:
```json
{
  "last_sweep_at": "2024-12-30T12:34:56Z",
  "users_monitored": 42,
  "kill_switches_activated": 2,
  "warnings_detected": 5,
  "errors": 0
}
```

### Cloud Logging Dashboard

Create a dashboard in Cloud Console with these queries:

**Query 1: Kill-Switch Activations**
```
resource.type="cloud_function"
resource.labels.function_name="operational_watchdog"
jsonPayload.message=~"KILL-SWITCH ACTIVATED"
```

**Query 2: All Watchdog Events**
```
resource.type="cloud_function"
resource.labels.function_name="operational_watchdog"
severity>=WARNING
```

## 🎛️ Configuration

### Adjust Thresholds

Edit `functions/utils/watchdog.py`:

```python
# Make watchdog more sensitive (trigger earlier)
LOSING_STREAK_THRESHOLD = 3  # Default: 5
MIN_LOSS_PERCENT = Decimal("0.25")  # Default: 0.5%
RAPID_DRAWDOWN_THRESHOLD = Decimal("3.0")  # Default: 5.0%

# Make watchdog less sensitive (fewer false positives)
LOSING_STREAK_THRESHOLD = 7  # Default: 5
MIN_LOSS_PERCENT = Decimal("1.0")  # Default: 0.5%
RAPID_DRAWDOWN_THRESHOLD = Decimal("10.0")  # Default: 5.0%
```

After changes, redeploy:
```bash
gcloud functions deploy operational_watchdog --source=.
```

## 🐛 Troubleshooting

### Issue: Watchdog Not Running

**Solution 1: Check Scheduler**
```bash
gcloud scheduler jobs describe operational_watchdog --location=us-central1
gcloud scheduler jobs list
```

**Solution 2: Check Function Logs**
```bash
gcloud functions logs read operational_watchdog --limit 50
```

### Issue: Gemini AI Failing

**Symptom**: Watchdog works but explanations are generic

**Solution**: Check Vertex AI permissions
```bash
# Test Gemini API directly
python3 << EOF
import vertexai
from vertexai.generative_models import GenerativeModel

vertexai.init(project="YOUR_PROJECT_ID", location="us-central1")
model = GenerativeModel("gemini-2.0-flash-exp")
response = model.generate_content("Test message")
print(response.text)
EOF
```

If this fails, grant permissions:
```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SERVICE_ACCOUNT" \
  --role="roles/aiplatform.user"
```

### Issue: False Positives (Too Sensitive)

**Solution**: Increase thresholds in `watchdog.py` and redeploy

### Issue: Missing Alerts

**Solution**: Check Firestore rules allow system writes
```javascript
// firestore.rules
match /users/{userId}/alerts/{alertId} {
  allow read: if request.auth.uid == userId;
  allow write: if true;  // Allow system writes
}
```

## 📚 Next Steps

1. **Integrate with Dashboard**: Add alert components to your frontend
2. **Customize Thresholds**: Adjust based on your risk tolerance
3. **Add Notifications**: Integrate with SMS/Email services
4. **Monitor Performance**: Set up Cloud Monitoring alerts
5. **Create Manual Override**: Build UI for re-enabling trading

## 🎓 Learn More

- [Full Documentation](./WATCHDOG_AGENT_README.md)
- [Architecture Details](./WATCHDOG_AGENT_README.md#architecture)
- [API Reference](./utils/watchdog.py)
- [Testing Guide](./WATCHDOG_AGENT_README.md#testing)

## ⚡ Performance Tips

1. **Reduce Frequency**: Change from `* * * * *` to `*/5 * * * *` (every 5 minutes)
2. **Limit Trade History**: Query only last 15 minutes instead of all trades
3. **Cache Market Data**: Avoid refetching market regime for each user
4. **Batch Processing**: Process users in batches of 10-20

## 🔐 Security Checklist

- [ ] Vertex AI permissions granted
- [ ] Firestore rules configured
- [ ] Service account has minimal required permissions
- [ ] Alerts are user-scoped (no cross-user leakage)
- [ ] Kill-switch is per-user (not global)

## 📞 Support

For help:
1. Check logs: `gcloud functions logs read operational_watchdog`
2. Review Firestore: `ops/watchdog_status`
3. Test locally: `python test_watchdog_manual.py`
4. Review [Full Documentation](./WATCHDOG_AGENT_README.md)
